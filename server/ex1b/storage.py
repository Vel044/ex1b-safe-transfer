"""Descriptor-relative access: never follow a client-supplied symlink."""
import contextlib
import hashlib
import os
import stat
from pathlib import Path

from .protocol import Fault


def parts(path, root_ok=False):
    if root_ok and path == "":
        return []
    if not isinstance(path, str) or len(path.encode()) > 4096 or "\0" in path or "\\" in path:
        raise Fault("PERMISSION", "路径无效")
    segments = path.split("/")
    if len(segments) > 32 or any(x in ("", ".", "..") or len(x.encode()) > 255 for x in segments):
        raise Fault("PERMISSION", "路径必须位于账户目录内")
    return segments


class Jail:
    def __init__(self, root):
        self.root = Path(root)
        self.fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    def close(self):
        os.close(self.fd)

    @contextlib.contextmanager
    def directory(self, segments, create=False):
        fd = os.dup(self.fd)
        try:
            for name in segments:
                if create:
                    try:
                        os.mkdir(name, 0o700, dir_fd=fd)
                    except FileExistsError:
                        pass
                next_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            yield fd
        except OSError as exc:
            raise file_fault(exc) from exc
        finally:
            os.close(fd)

    def mkdir(self, path):
        with self.directory(parts(path), create=True):
            pass

    def delete(self, path):
        segments = parts(path)
        budget = [10000]
        def remove(parent, name, depth):
            budget[0] -= 1
            if budget[0] < 0 or depth > 32:
                raise Fault("LIMIT", "删除目录超过条目或深度限制")
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                try:
                    for child in os.listdir(fd):
                        remove(fd, child, depth+1)
                finally:
                    os.close(fd)
                os.rmdir(name, dir_fd=parent)
            else:
                os.unlink(name, dir_fd=parent)
        with self.directory(segments[:-1]) as parent:
            remove(parent, segments[-1], len(segments))
            os.fsync(parent)

    def listing(self, path, cursor):
        with self.directory(parts(path, True)) as fd:
            entries = []
            with os.scandir(fd) as iterator:
                for entry in iterator:
                    if len(entries) >= 10000:
                        raise Fault("LIMIT", "目录条目超过10000个")
                    info = entry.stat(follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode) or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                        continue
                    entries.append({"name": entry.name, "directory": stat.S_ISDIR(info.st_mode), "size": info.st_size, "modified": info.st_mtime})
            entries.sort(key=lambda e: (not e["directory"], e["name"]))
            return {"entries": entries[cursor:cursor+100], "next": cursor+100 if cursor+100 < len(entries) else None}

    def exists(self, path):
        segments = parts(path)
        with self.directory(segments[:-1]) as fd:
            try:
                os.stat(segments[-1], dir_fd=fd, follow_symlinks=False)
                return True
            except FileNotFoundError:
                return False

    @contextlib.contextmanager
    def file(self, path):
        segments = parts(path)
        with self.directory(segments[:-1]) as parent:
            try:
                fd = os.open(segments[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            except OSError as exc:
                raise file_fault(exc) from exc
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise Fault("PERMISSION", "只允许普通文件，不允许链接或设备")
                yield fd
            finally:
                os.close(fd)

    def identity(self, path, prefix=None):
        with self.file(path) as fd:
            info = os.fstat(fd)
            digest = digest_fd(fd, prefix)
            after = os.fstat(fd)
            if (info.st_size, info.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise Fault("CHANGED", "源文件发生变化")
            return info.st_size, digest

    def read(self, path, offset, length):
        with self.file(path) as fd:
            return os.pread(fd, length, offset)

    def commit(self, temporary, path):
        segments = parts(path)
        with self.directory(segments[:-1]) as parent:
            try:
                # linkat creates the final name atomically and MUST fail if it exists.
                try:
                    os.link(temporary, segments[-1], dst_dir_fd=parent, follow_symlinks=False)
                except FileExistsError:
                    source = os.stat(temporary, follow_symlinks=False)
                    target = os.stat(segments[-1], dir_fd=parent, follow_symlinks=False)
                    if (source.st_dev,source.st_ino) != (target.st_dev,target.st_ino):
                        raise
                os.fsync(parent)
            except OSError as exc:
                raise file_fault(exc) from exc
        os.unlink(temporary)


def digest_fd(fd, length=None):
    digest = hashlib.sha256()
    position = 0
    while length is None or position < length:
        data = os.pread(fd, min(1024*1024, length-position) if length is not None else 1024*1024, position)
        if not data:
            break
        digest.update(data)
        position += len(data)
    if length is not None and position != length:
        raise Fault("INTEGRITY", "续传文件长度不符")
    return digest.hexdigest()


def partial_identity(path, length):
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    try:
        if os.fstat(fd).st_size < length:
            raise Fault("INTEGRITY", "临时文件长度小于检查点")
        os.ftruncate(fd, length)
        return digest_fd(fd, length)
    finally:
        os.close(fd)


def write_chunk(path, offset, data):
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    try:
        if os.fstat(fd).st_size < offset:
            raise Fault("INTEGRITY", "临时文件检查点损坏")
        os.ftruncate(fd, offset)
        written = 0
        while written < len(data):
            count = os.pwrite(fd, data[written:], offset+written)
            if not count:
                raise Fault("IO", "文件写入未取得进展")
            written += count
        os.fsync(fd)
    finally:
        os.close(fd)


def file_fault(exc):
    if isinstance(exc, FileExistsError):
        return Fault("CONFLICT", "已有同名文件，请改名后重试")
    if isinstance(exc, FileNotFoundError):
        return Fault("NOT_FOUND", "文件或目录不存在")
    return Fault("IO", f"文件访问失败（{exc.errno}）")
