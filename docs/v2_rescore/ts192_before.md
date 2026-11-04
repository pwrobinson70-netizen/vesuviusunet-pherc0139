{"tool_version": "0.1.0", "input": "/tmp/claude-0/-home-user/558f9a8d-138c-51b9-a229-312e623363a6/scratchpad/runs/ts192_before/crushed-hard_t1-mid", "output": "/tmp/claude-0/-home-user/558f9a8d-138c-51b9-a229-312e623363a6/scratchpad/runs/ts192_before/crushed-hard_t1-mid_fixed", "audit": "/tmp/claude-0/-home-user/558f9a8d-138c-51b9-a229-312e623363a6/scratchpad/runs/ts192_before/crushed-hard_t1-mid_audit.json", "audit_trace": "crushed-hard_t1-mid", "repaired": true, "confirmed": [{"axis": "cols", "line": 21, "orth": null, "source": "winding_jumps", "direction": "outward", "height": 92.0, "move_vox": 10.519905743732732}], "unconfirmed": [], "pitch_vox": 8.625, "volume": "/tmp/claude-0/-home-user/558f9a8d-138c-51b9-a229-312e623363a6/scratchpad/runs/ts192_before/crushed-hard_vol.npy", "n_valid": 1356, "n_moved_over_half_voxel": 94, "fraction_moved": 0.06932153392330384, "max_move_vox": 10.519905743732732, "median_move_of_moved_vox": 4.479285291349936, "n_unsnapped": 2, "n_outliers_replaced": 16, "n_unreached": 54, "axes": {"cols": {"low_to_high": 19, "n_switches": 1}}}
| phantom | seed | points | area (vx^2) | on correct turn before | after repair | verdict before | verdict after | failing checks before |
|---|---|---|---|---|---|---|---|---|
| crushed | t1-mid | 2501 | 22120 | 100.0% | 100.0% (not repaired) | PASS | PASS |  |
| crushed | t2-mid | 2501 | 21850 | 100.0% | 100.0% (not repaired) | PASS | PASS |  |
| crushed | t2-low | 1974 | 17065 | 100.0% | 100.0% (not repaired) | PASS | PASS |  |
| folded | t1-mid | 2501 | 21824 | 100.0% | 100.0% (not repaired) | PASS | PASS |  |
| folded | t2-mid | 2501 | 21573 | 100.0% | 100.0% (not repaired) | PASS | PASS |  |
| folded | t2-low | 1968 | 16991 | 100.0% | 100.0% (not repaired) | PASS | PASS |  |
| delaminated | t1-mid | 2501 | 21826 | 100.0% | 100.0% (not repaired) | PASS | PASS |  |
| delaminated | t2-mid | 2501 | 21838 | 100.0% | 100.0% (not repaired) | PASS | PASS |  |
| delaminated | t2-low | 1968 | 17239 | 100.0% | 100.0% (not repaired) | PASS | PASS |  |
| torn | t1-mid | 2501 | 21835 | 100.0% | 100.0% (not repaired) | PASS | PASS |  |
| torn | t2-mid | 2501 | 21703 | 100.0% | 100.0% (not repaired) | PASS | PASS |  |
| torn | t2-low | 1968 | 16988 | 100.0% | 100.0% (not repaired) | PASS | PASS |  |
| gappy | t1-mid | 2501 | 21825 | 100.0% | 100.0% (not repaired) | PASS | PASS |  |
| gappy | t2-mid | 2460 | 20973 | 100.0% | 100.0% (not repaired) | PASS | PASS |  |
| gappy | t2-low | 1914 | 16324 | 100.0% | 100.0% (not repaired) | PASS | PASS |  |
| crushed-hard | t1-mid | 1356 | 10695 | 84.1% | 87.4% | FAIL | FAIL | winding_jumps |
| crushed-hard | t2-mid | 1775 | 14531 | 89.0% | 89.0% (not repaired) | PASS | PASS |  |
| crushed-hard | t2-low | - | - | - | - | - | - | seed rejected: seed is in a gap: no sheet peak within +/- 2.0 voxels (0.25 x pitch 8.0) along the normal; move the seed onto a sheet (the tracer never jumps to the neighbouring sheet) |

