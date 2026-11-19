--------------------------- MODULE SFT1Transfer ---------------------------
EXTENDS Naturals, Sequences
CONSTANTS Uploads, WrongReply
Tasks == {"A", "B"}
Numbers == {1, 2}
Source(t) == IF t = "A" THEN <<"A0", "A1">> ELSE <<"B0", "B1">>
Prefix(t, n) == SubSeq(Source(t), 1, n)
Zeros == [t \in Tasks |-> 0]

\* disk is the receiver's temporary file (server for PUT, client for GET).
\* cp is its durable checkpoint; pos is the agreed next block position.
VARIABLES disk, cp, pos, pending, calls, replies, published, online, breaks
vars == <<disk, cp, pos, pending, calls, replies, published, online, breaks>>
Init == /\ disk = [t \in Tasks |-> <<>>] /\ cp = Zeros /\ pos = Zeros
        /\ pending = Zeros /\ calls = {} /\ replies = {} /\ published = {}
        /\ online = TRUE /\ breaks = 0

Issue(t, n) ==
    /\ online /\ t \notin published /\ pending[t] = 0 /\ pos[t] < Len(Source(t))
    /\ \A u \in Tasks: pending[u] # n
    /\ pending' = [pending EXCEPT ![t] = n]
    /\ calls' = calls \cup {[id |-> t, request |-> n, offset |-> pos[t],
         payload |-> IF t \in Uploads THEN Source(t)[pos[t]+1] ELSE "READ"]}
    /\ UNCHANGED <<disk, cp, pos, replies, published, online, breaks>>

WriteUpload(m) ==
    /\ m.id \in Uploads /\ m.offset = cp[m.id] /\ m.offset = Len(disk[m.id])
    /\ disk' = [disk EXCEPT ![m.id] = Append(@, m.payload)]
    /\ UNCHANGED <<cp, pos, pending, calls, replies, published, online, breaks>>

Checkpoint(t) ==
    /\ online /\ Len(disk[t]) = cp[t] + 1
    /\ cp' = [cp EXCEPT ![t] = Len(disk[t])]
    /\ UNCHANGED <<disk, pos, pending, calls, replies, published, online, breaks>>

Respond(m) ==
    /\ IF m.id \in Uploads THEN cp[m.id] = m.offset + 1
                           ELSE m.offset = pos[m.id]
    /\ LET r == IF m.id \in Uploads
                THEN [request |-> m.request, offset |-> cp[m.id], payload |-> "ACK"]
                ELSE [request |-> m.request, offset |-> m.offset,
                      payload |-> Source(m.id)[m.offset+1]]
       IN replies' = replies \cup {r}
    /\ calls' = calls \ {m}
    /\ UNCHANGED <<disk, cp, pos, pending, published, online, breaks>>

Deliver(r, t) ==
    /\ pending[t] # 0 /\ (pending[t] = r.request \/ WrongReply)
    /\ IF t \in Uploads
       THEN /\ r.payload = "ACK" /\ r.offset = pos[t]+1
            /\ pos' = [pos EXCEPT ![t] = r.offset]
            /\ pending' = [pending EXCEPT ![t] = 0] /\ UNCHANGED disk
       ELSE /\ r.payload # "ACK" /\ r.offset = pos[t] /\ r.offset = Len(disk[t])
            /\ disk' = [disk EXCEPT ![t] = Append(@, r.payload)]
            /\ UNCHANGED <<pos, pending>>
    /\ replies' = replies \ {r}
    /\ UNCHANGED <<cp, calls, published, online, breaks>>

\* The download ACK round trip is one action after the local checkpoint.
ConfirmDownload(t) ==
    /\ online /\ t \notin Uploads /\ cp[t] = pos[t]+1
    /\ pos' = [pos EXCEPT ![t] = cp[t]] /\ pending' = [pending EXCEPT ![t] = 0]
    /\ UNCHANGED <<disk, cp, calls, replies, published, online, breaks>>

Finish(t) ==
    /\ online /\ pending[t] = 0 /\ t \notin published
    /\ pos[t] = Len(Source(t)) /\ disk[t] = Source(t)
    /\ published' = published \cup {t}
    /\ UNCHANGED <<disk, cp, pos, pending, calls, replies, online, breaks>>

Disconnect ==
    /\ online /\ breaks = 0 /\ breaks' = 1 /\ online' = FALSE
    /\ calls' = {} /\ replies' = {} /\ pending' = Zeros
    /\ UNCHANGED <<disk, cp, pos, published>>
Reconnect ==
    /\ ~online /\ \A t \in Tasks: SubSeq(disk[t], 1, cp[t]) = Prefix(t, cp[t])
    /\ disk' = [t \in Tasks |-> SubSeq(disk[t], 1, cp[t])]
    /\ pos' = cp /\ online' = TRUE
    /\ UNCHANGED <<cp, pending, calls, replies, published, breaks>>

Advance == \/ \E t \in Tasks, n \in Numbers: Issue(t, n)
           \/ \E m \in calls: WriteUpload(m) \/ Respond(m)
           \/ \E r \in replies, t \in Tasks: Deliver(r, t)
           \/ \E t \in Tasks: Checkpoint(t) \/ ConfirmDownload(t) \/ Finish(t)
Next == Advance \/ Disconnect \/ Reconnect
Spec == Init /\ [][Next]_vars /\ WF_vars(Advance) /\ WF_vars(Reconnect)

CorrectPrefix == \A t \in Tasks: disk[t] = Prefix(t, Len(disk[t]))
DurableProgress == \A t \in Tasks: pos[t] <= cp[t] /\ cp[t] <= Len(disk[t])
PublishedContent == \A t \in published: disk[t] = Source(t)
BothComplete == <>(published = Tasks)
=============================================================================
