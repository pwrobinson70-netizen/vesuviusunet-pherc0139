{"tool_version": "0.1.0", "input": "/tmp/claude-0/-home-user/558f9a8d-138c-51b9-a229-312e623363a6/scratchpad/runs/ts256_after/merged_t1-mid", "output": "/tmp/claude-0/-home-user/558f9a8d-138c-51b9-a229-312e623363a6/scratchpad/runs/ts256_after/merged_t1-mid_fixed", "audit": "/tmp/claude-0/-home-user/558f9a8d-138c-51b9-a229-312e623363a6/scratchpad/runs/ts256_after/merged_t1-mid_audit.json", "audit_trace": "merged_t1-mid", "repaired": false, "confirmed": [], "unconfirmed": [{"axis": "rows", "line": 30, "orth": 23.0, "source": "switch_finder", "direction": "inward", "height": 123.0, "move_vox": 0.2480144751782327}, {"axis": "rows", "line": 42, "orth": 23.0, "source": "switch_finder", "direction": "outward", "height": 171.0, "move_vox": 0.24111445484304508}], "note": "no switch confirmed: the repair moved no point at any reported place by >= --confirm-pitch x pitch, so the report is a false alarm or mislocated; input copied byte for byte, verdict NOT changed"}
{"tool_version": "0.1.0", "input": "/tmp/claude-0/-home-user/558f9a8d-138c-51b9-a229-312e623363a6/scratchpad/runs/ts256_after/merged_t2-mid", "output": "/tmp/claude-0/-home-user/558f9a8d-138c-51b9-a229-312e623363a6/scratchpad/runs/ts256_after/merged_t2-mid_fixed", "audit": "/tmp/claude-0/-home-user/558f9a8d-138c-51b9-a229-312e623363a6/scratchpad/runs/ts256_after/merged_t2-mid_audit.json", "audit_trace": "merged_t2-mid", "repaired": false, "confirmed": [], "unconfirmed": [{"axis": "rows", "line": 30, "orth": 20.0, "source": "switch_finder", "direction": "outward", "height": 123.0, "move_vox": 0.17138451595364776}, {"axis": "rows", "line": 42, "orth": 20.0, "source": "switch_finder", "direction": "inward", "height": 171.0, "move_vox": 0.2512286738309645}], "note": "no switch confirmed: the repair moved no point at any reported place by >= --confirm-pitch x pitch, so the report is a false alarm or mislocated; input copied byte for byte, verdict NOT changed"}
| phantom | seed | points | area (vx^2) | on correct turn before | after repair | verdict before | verdict after | failing checks before |
|---|---|---|---|---|---|---|---|---|
| round | t1-mid | 2501 | 38419 | 100.0% | 100.0% (not repaired) | PASS | PASS |  |
| round | t2-mid | 2501 | 38437 | 100.0% | 100.0% (not repaired) | PASS | PASS |  |
| round | t2-low | 1968 | 30102 | 100.0% | 100.0% (not repaired) | PASS | PASS |  |
| mild | t1-mid | 2501 | 38745 | 100.0% | 100.0% (not repaired) | PASS | PASS |  |
| mild | t2-mid | 2501 | 38679 | 100.0% | 100.0% (not repaired) | PASS | PASS |  |
| mild | t2-low | 1968 | 29891 | 100.0% | 100.0% (not repaired) | PASS | PASS |  |
| bad | t1-mid | 2501 | 38851 | 100.0% | 100.0% (not repaired) | NOT JUDGED | NOT JUDGED |  |
| bad | t2-mid | 2501 | 38700 | 100.0% | 100.0% (not repaired) | NOT JUDGED | NOT JUDGED |  |
| bad | t2-low | 1998 | 30197 | 100.0% | 100.0% (not repaired) | NOT JUDGED | NOT JUDGED |  |
| merged | t1-mid | 2499 | 38602 | 99.1% | 99.1% (not repaired) | FAIL | FAIL | switch_finder |
| merged | t2-mid | 2501 | 38732 | 100.0% | 100.0% (not repaired) | FAIL | FAIL | switch_finder |
| merged | t2-low | 1947 | 28907 | 93.0% | 93.0% (not repaired) | PASS | PASS |  |

