#if DEBUG
import AppKit
import ScreenCaptureKit
import AVFoundation
import UniformTypeIdentifiers

/// Course evidence only; excluded from the Release application.
/// SCShareableContent.currentProcess exposes only this process's capturable windows.
@available(macOS 15.0, *)
@MainActor final class DemoCapture:NSObject {
    static let shared=DemoCapture()
    var report:((String)->Void)?
    private var destination:URL?
    private var recording=false
    private var recordingActive=false
    private var stopRequested=false

    func begin(recording:Bool){
        guard !recordingActive else{report?("请先停止当前录制");return}
        let panel=NSSavePanel()
        panel.allowedContentTypes=recording ? [.mpeg4Movie] : [.png]
        panel.nameFieldStringValue=recording ? "native-demo.mp4" : "native-client.png"
        guard panel.runModal() == .OK,let url=panel.url else{return}
        destination=url;self.recording=recording
        Task{
            do{
                let content=try await SCShareableContent.currentProcess
                let number=NSApp.windows.first(where:{$0.isVisible && $0.title == "SFT1 Transfer"})?.windowNumber
                guard let window=content.windows.first(where:{Int($0.windowID) == number && $0.owningApplication?.processID == getpid()}) else {
                    report?("未找到本应用可采集的窗口");return
                }
                await capture(SCContentFilter(desktopIndependentWindow:window))
            }catch{report?("窗口采集失败：\(error.localizedDescription)")}
        }
    }
    private func capture(_ filter:SCContentFilter)async{
        guard let destination else{return}
        do{
            let configuration=SCStreamConfiguration()
            let window=NSApp.windows.first(where:{$0.isVisible && $0.title == "SFT1 Transfer"})
            let size=window?.frame.size ?? CGSize(width:1220,height:800)
            let scale=window?.screen?.backingScaleFactor ?? 2
            configuration.width=max(2,Int(size.width*scale)/2*2)
            configuration.height=max(2,Int(size.height*scale)/2*2)
            configuration.showsCursor=false
            configuration.capturesAudio=false
            configuration.captureMicrophone=false
            configuration.minimumFrameInterval=CMTime(value:1,timescale:15)
            if recording{
                try await recordFrames(filter,configuration:configuration,destination:destination)
            }else{
                let image=try await SCScreenshotManager.captureImage(contentFilter:filter,configuration:configuration)
                guard let bytes=NSBitmapImageRep(cgImage:image).representation(using:.png,properties:[:]) else{return}
                try bytes.write(to:destination)
                report?("已保存实际窗口图像")
            }
        }catch{recordingActive=false;report?("窗口采集失败：\(error.localizedDescription)")}
    }
    func stop(){
        stopRequested=true
    }
    private func recordFrames(_ filter:SCContentFilter,configuration:SCStreamConfiguration,destination:URL) async throws {
        let width=1280,height=840
        let writer=try AVAssetWriter(outputURL:destination,fileType:.mp4)
        let input=AVAssetWriterInput(mediaType:.video,outputSettings:[AVVideoCodecKey:AVVideoCodecType.h264,AVVideoWidthKey:width,AVVideoHeightKey:height])
        input.expectsMediaDataInRealTime=true
        let attrs:[String:Any]=[kCVPixelBufferPixelFormatTypeKey as String:kCVPixelFormatType_32BGRA,kCVPixelBufferWidthKey as String:width,kCVPixelBufferHeightKey as String:height,kCVPixelBufferCGImageCompatibilityKey as String:true,kCVPixelBufferCGBitmapContextCompatibilityKey as String:true]
        let adaptor=AVAssetWriterInputPixelBufferAdaptor(assetWriterInput:input,sourcePixelBufferAttributes:attrs)
        writer.add(input)
        guard writer.startWriting() else{throw writer.error ?? NSError(domain:"Capture",code:1)}
        writer.startSession(atSourceTime:.zero)
        recordingActive=true;stopRequested=false
        report?("正在录制本应用窗口")
        let start=Date()
        while !stopRequested {
            let image=try await SCScreenshotManager.captureImage(contentFilter:filter,configuration:configuration)
            if input.isReadyForMoreMediaData {
                var raw:CVPixelBuffer?
                guard CVPixelBufferCreate(kCFAllocatorDefault,width,height,kCVPixelFormatType_32BGRA,attrs as CFDictionary,&raw) == kCVReturnSuccess,let buffer=raw else{throw NSError(domain:"Capture",code:2)}
                CVPixelBufferLockBaseAddress(buffer,[])
                let flags=CGImageAlphaInfo.premultipliedFirst.rawValue|CGBitmapInfo.byteOrder32Little.rawValue
                if let context=CGContext(data:CVPixelBufferGetBaseAddress(buffer),width:width,height:height,bitsPerComponent:8,bytesPerRow:CVPixelBufferGetBytesPerRow(buffer),space:CGColorSpaceCreateDeviceRGB(),bitmapInfo:flags){
                    context.draw(image,in:CGRect(x:0,y:0,width:width,height:height))
                }
                CVPixelBufferUnlockBaseAddress(buffer,[])
                guard adaptor.append(buffer,withPresentationTime:CMTime(seconds:Date().timeIntervalSince(start),preferredTimescale:600)) else{throw writer.error ?? NSError(domain:"Capture",code:3)}
            }
            try await Task.sleep(for:.milliseconds(180))
        }
        input.markAsFinished()
        await writer.finishWriting()
        recordingActive=false
        guard writer.status == .completed else{throw writer.error ?? NSError(domain:"Capture",code:4)}
        report?("窗口录制已保存")
    }
}
#endif
