--------------------------- MODULE SFT1Upload ---------------------------
EXTENDS Naturals, TLC
CONSTANTS Tasks, Blocks, AllowControls, AllowCorruption, MaxCrashes, Bug
VARIABLE x
vars == <<x>>
Phases == {"idle", "written", "checkpointed", "ack", "verified", "linked", "reply"}
Statuses == {"active", "paused", "cancelled", "failed", "complete"}
Init == x = [t \in Tasks |-> [disk |-> 0, cp |-> 0, ack |-> 0,
    good |-> TRUE, cpGood |-> TRUE, published |-> FALSE, status |-> "active",
    phase |-> "idle", online |-> TRUE, crashes |-> 0, breach |-> FALSE]]
Running(t) == x[t].online /\ x[t].status = "active" /\ ~x[t].published
Receive(t, valid) ==
    /\ Running(t) /\ x[t].phase = "idle" /\ x[t].ack = x[t].cp
    /\ x[t].cp < Blocks /\ (valid \/ AllowCorruption)
    /\ x' = [x EXCEPT ![t].disk = @ + 1, ![t].good = @ /\ valid,
                      ![t].phase = "written"]
Checkpoint(t) ==
    /\ Running(t) /\ x[t].phase = "written"
    /\ x' = [x EXCEPT ![t].cp = x[t].disk, ![t].cpGood = x[t].good, ![t].phase = "checkpointed"]
SendAck(t) ==
    /\ Running(t)
    /\ (x[t].phase = "checkpointed" \/ (Bug = "early_ack" /\ x[t].phase = "written"))
    /\ x' = [x EXCEPT ![t].ack = x[t].disk, ![t].phase = "ack"]
ConsumeAck(t) ==
    /\ Running(t) /\ x[t].phase = "ack"
    /\ x' = [x EXCEPT ![t].phase = "idle"]
Duplicate(t) ==
    /\ Running(t) /\ x[t].phase = "idle" /\ x[t].cp > 0
    /\ IF Bug = "duplicate_append"
       THEN x' = [x EXCEPT ![t].disk = @ + 1, ![t].cp = @ + 1, ![t].good = FALSE]
       ELSE x' = [x EXCEPT ![t].ack = x[t].cp]
Verify(t) ==
    /\ Running(t) /\ x[t].phase = "idle" /\ x[t].cp = Blocks
    /\ IF x[t].good
       THEN x' = [x EXCEPT ![t].phase = "verified"]
       ELSE x' = [x EXCEPT ![t].status = "failed"]
Publish(t) ==
    /\ Running(t)
    /\ (x[t].phase = "verified" \/ (Bug = "early_finish" /\ x[t].phase = "idle"))
    /\ x' = [x EXCEPT ![t].published = TRUE, ![t].phase = "linked"]
Complete(t) ==
    /\ x[t].online /\ x[t].published /\ x[t].phase = "linked"
    /\ x' = [x EXCEPT ![t].status = "complete", ![t].phase = "reply"]
Crash(t) ==
    /\ x[t].online /\ x[t].crashes < MaxCrashes
    /\ x' = [x EXCEPT ![t].online = FALSE, ![t].phase = "idle", ![t].crashes = @ + 1]
Reconnect(t) ==
    /\ ~x[t].online
    /\ x' = [x EXCEPT ![t].online = TRUE,
          ![t].disk = IF x[t].published THEN x[t].disk ELSE x[t].cp,
          ![t].ack = x[t].cp, ![t].good = x[t].cpGood,
          ![t].status = IF x[t].published THEN "complete" ELSE x[t].status]
Pause(t) ==
    /\ AllowControls /\ Running(t) /\ x[t].phase = "idle"
    /\ x' = [x EXCEPT ![t].status = "paused"]
Resume(t, owner) ==
    /\ x[t].online /\ x[t].status \in {"active", "paused"} /\ ~x[t].published
    /\ x[t].phase = "idle" /\ (owner \/ Bug = "no_owner")
    /\ x' = [x EXCEPT ![t].status = "active", ![t].ack = x[t].cp,
                       ![t].disk = x[t].cp, ![t].breach = @ \/ ~owner]
Cancel(t) ==
    /\ AllowControls /\ x[t].online /\ ~x[t].published
    /\ x[t].phase = "idle" /\ x[t].status \in {"active", "paused"}
    /\ x' = [x EXCEPT ![t].status = "cancelled"]
Progress(t) == Receive(t, TRUE) \/ Checkpoint(t) \/ SendAck(t) \/ ConsumeAck(t)
               \/ Verify(t) \/ Publish(t) \/ Complete(t)
Next == \E t \in Tasks: Progress(t) \/ Receive(t, FALSE) \/ Duplicate(t)
        \/ Crash(t) \/ Reconnect(t) \/ Pause(t) \/ Resume(t, TRUE)
        \/ Resume(t, FALSE) \/ Cancel(t)
Spec == Init /\ [][Next]_vars
FairSpec == Spec /\ \A t \in Tasks: WF_vars(Progress(t)) /\ WF_vars(Reconnect(t))
TypeOK == \A t \in Tasks:
    /\ x[t].disk \in Nat /\ x[t].cp \in Nat /\ x[t].ack \in Nat
    /\ x[t].good \in BOOLEAN /\ x[t].cpGood \in BOOLEAN /\ x[t].published \in BOOLEAN
    /\ x[t].online \in BOOLEAN /\ x[t].breach \in BOOLEAN
    /\ x[t].status \in Statuses /\ x[t].phase \in Phases
    /\ x[t].crashes \in 0..MaxCrashes
Bounds == \A t \in Tasks: x[t].ack <= x[t].cp /\ x[t].cp <= x[t].disk /\ x[t].disk <= Blocks
AckDurable == \A t \in Tasks: x[t].ack <= x[t].cp
PublishedIntegrity == \A t \in Tasks: x[t].published =>
    (x[t].disk = Blocks /\ x[t].cp = Blocks /\ x[t].good)
CompleteIntegrity == \A t \in Tasks: x[t].status = "complete" => x[t].published
Isolation == \A t \in Tasks: ~x[t].breach
TerminalStable == \A t \in Tasks:
    /\ [](x[t].status = "complete" => [](x[t].status = "complete"))
    /\ [](x[t].status = "cancelled" => [](x[t].status = "cancelled"))
    /\ [](x[t].status = "failed" => [](x[t].status = "failed"))
NoCompletion == ~\E t \in Tasks: x[t].status = "complete"
EventuallyComplete == \A t \in Tasks: <>(x[t].status = "complete")
=============================================================================
