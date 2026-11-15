# Evaluation results (2026-11-15)

- Machine: Windows-11-10.0.26300-SP0, Intel64 Family 6 Model 197 Stepping 2, GenuineIntel
- Documents: pump-station-procedure-v1.pdf, emergency-response-plan.pdf (sample files in web/public/samples)
- Search mode: hybrid (keywords + meaning)
- Questions: 20 in scope, 2 out of scope

## Retrieval: is the right file and page among the top results?

- Passages in the test corpus: 5 (small, so top 5 would always be true)
- Top 1: 20 of 20
- Top 3: 20 of 20

| Question | Expected | Rank found |
|---|---|---|
| Who owns the pump station procedure? | pump-station-procedure-v1.pdf p.1 | 1 |
| How often is the procedure reviewed? | pump-station-procedure-v1.pdf p.1 | 1 |
| Which pumps does the procedure cover? | pump-station-procedure-v1.pdf p.1 | 1 |
| Are visitors allowed in the pump hall on their own? | pump-station-procedure-v1.pdf p.1 | 1 |
| Which valve is closed first before maintenance? | pump-station-procedure-v1.pdf p.2 | 1 |
| What must the pressure gauge read before a flange is opened? | pump-station-procedure-v1.pdf p.2 | 1 |
| How long should operators wait before touching the pump casing? | pump-station-procedure-v1.pdf p.2 | 1 |
| How many people confirm the lock-out? | pump-station-procedure-v1.pdf p.2 | 1 |
| Where is the emergency stop button? | pump-station-procedure-v1.pdf p.3 | 1 |
| Which extension do I call after an emergency shutdown? | pump-station-procedure-v1.pdf p.3 | 1 |
| How long must the pump logbook be kept? | pump-station-procedure-v1.pdf p.3 | 1 |
| How often should the seal be inspected for leakage? | pump-station-procedure-v1.pdf p.3 | 1 |
| Where is the assembly point? | emergency-response-plan.pdf p.1 | 1 |
| What does a gas leak alarm sound like? | emergency-response-plan.pdf p.1 | 1 |
| Who gives the all-clear? | emergency-response-plan.pdf p.1 | 1 |
| How often are fire drills held? | emergency-response-plan.pdf p.2 | 1 |
| What is the emergency phone number? | emergency-response-plan.pdf p.2 | 1 |
| Where are the first aid kits? | emergency-response-plan.pdf p.2 | 1 |
| Within how long must a near miss be reported? | emergency-response-plan.pdf p.2 | 1 |
| What colour vests do fire marshals wear? | emergency-response-plan.pdf p.2 | 1 |

## Answers from llama3.2:3b

- Correct (expected fact appears): 20 of 20
- With at least one citation: 20 of 20
- Refused when the documents had no answer: 2 of 2
- Time per answer: median 8.9 s, slowest 10.9 s

| Question | Correct | Seconds |
|---|---|---|
| Who owns the pump station procedure? | yes | 10.9 |
| How often is the procedure reviewed? | yes | 9.0 |
| Which pumps does the procedure cover? | yes | 9.0 |
| Are visitors allowed in the pump hall on their own? | yes | 8.1 |
| Which valve is closed first before maintenance? | yes | 10.1 |
| What must the pressure gauge read before a flange is opened? | yes | 9.6 |
| How long should operators wait before touching the pump casing? | yes | 8.1 |
| How many people confirm the lock-out? | yes | 4.0 |
| Where is the emergency stop button? | yes | 9.9 |
| Which extension do I call after an emergency shutdown? | yes | 9.8 |
| How long must the pump logbook be kept? | yes | 9.4 |
| How often should the seal be inspected for leakage? | yes | 8.8 |
| Where is the assembly point? | yes | 10.7 |
| What does a gas leak alarm sound like? | yes | 8.0 |
| Who gives the all-clear? | yes | 9.6 |
| How often are fire drills held? | yes | 10.0 |
| What is the emergency phone number? | yes | 8.9 |
| Where are the first aid kits? | yes | 8.0 |
| Within how long must a near miss be reported? | yes | 8.2 |
| What colour vests do fire marshals wear? | yes | 7.7 |
| What is the capital of France? | yes | 3.7 |
| How much does a P-101 pump cost? | yes | 3.8 |
