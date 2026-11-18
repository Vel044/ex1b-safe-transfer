-------------------------- MODULE SFT1Download --------------------------
EXTENDS Naturals, TLC
CONSTANTS Blocks, MaxCrashes, AllowChange, Bug
VARIABLES disk, saved, server, phase, online, crashes, sourceOK, prefixOK, checked, published
vars == <<disk, saved, server, phase, online, crashes, sourceOK, prefixOK, checked, published>>
Init == /\ disk = 0 /\ saved = 0 /\ server = 0 /\ phase = "read"
        /\ online = TRUE /\ crashes = 0 /\ sourceOK = TRUE /\ prefixOK = TRUE
        /\ checked = FALSE /\ published = FALSE
ReadWrite == /\ online /\ phase = "read" /\ saved < Blocks
    /\ disk' = saved + 1 /\ phase' = "save"
    /\ UNCHANGED <<saved, server, online, crashes, sourceOK, prefixOK, checked, published>>
Save == /\ online /\ phase = "save" /\ saved' = disk /\ phase' = "ack"
    /\ UNCHANGED <<disk, server, online, crashes, sourceOK, prefixOK, checked, published>>
Ack == /\ online /\ phase = "ack" /\ server' = saved /\ phase' = "read"
    /\ UNCHANGED <<disk, saved, online, crashes, sourceOK, prefixOK, checked, published>>
Verify == /\ online /\ phase = "read" /\ saved = Blocks
    /\ sourceOK /\ prefixOK /\ checked' = TRUE /\ phase' = "finish"
    /\ UNCHANGED <<disk, saved, server, online, crashes, sourceOK, prefixOK, published>>
Finish == /\ online /\ phase = "finish" /\ sourceOK /\ server = Blocks
    /\ phase' = "commit"
    /\ UNCHANGED <<disk, saved, server, online, crashes, sourceOK, prefixOK, checked, published>>
Commit == /\ online /\ phase = "commit" /\ checked
    /\ published' = TRUE /\ phase' = "done"
    /\ UNCHANGED <<disk, saved, server, online, crashes, sourceOK, prefixOK, checked>>
Crash == /\ online /\ ~published /\ crashes < MaxCrashes
    /\ online' = FALSE /\ crashes' = crashes + 1 /\ phase' = "resume"
    /\ UNCHANGED <<disk, saved, server, sourceOK, prefixOK, checked, published>>
Resume == /\ ~online /\ ((sourceOK /\ prefixOK) \/ Bug = "unchecked_resume")
    /\ online' = TRUE /\ disk' = saved /\ server' = saved
    /\ phase' = "read" /\ checked' = FALSE
    /\ UNCHANGED <<saved, crashes, sourceOK, prefixOK, published>>
Change == /\ AllowChange /\ ~online /\ sourceOK /\ sourceOK' = FALSE
    /\ UNCHANGED <<disk, saved, server, phase, online, crashes, prefixOK, checked, published>>
BadPrefix == /\ AllowChange /\ ~online /\ prefixOK /\ prefixOK' = FALSE
    /\ UNCHANGED <<disk, saved, server, phase, online, crashes, sourceOK, checked, published>>
Progress == ReadWrite \/ Save \/ Ack \/ Verify \/ Finish \/ Commit
Next == Progress \/ Crash \/ Resume \/ Change \/ BadPrefix
Spec == Init /\ [][Next]_vars
FairSpec == Spec /\ WF_vars(Progress) /\ WF_vars(Resume)
TypeOK == /\ disk \in 0..Blocks /\ saved \in 0..Blocks /\ server \in 0..Blocks
    /\ online \in BOOLEAN /\ crashes \in 0..MaxCrashes
    /\ sourceOK \in BOOLEAN /\ prefixOK \in BOOLEAN
    /\ checked \in BOOLEAN /\ published \in BOOLEAN
    /\ phase \in {"read", "save", "ack", "finish", "commit", "done", "resume"}
CheckpointSafe == server <= saved /\ saved <= disk
PublishSafe == published => (saved = Blocks /\ disk = Blocks /\ checked)
ResumeIdentity == online => (sourceOK /\ prefixOK)
NoCompletion == ~published
EventuallyComplete == <>published
=============================================================================
