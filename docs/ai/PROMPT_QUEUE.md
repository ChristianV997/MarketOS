# Gate-Driven Prompt Queue

Updated: 2026-09-01

## Prompt-Card Template
All future agent tasks must conform to this compact prompt-card specification:

- **exact base SHA:** [SHA]
- **branch:** [branch_name]
- **exclusive files:** [allowed_paths]
- **forbidden files:** [restricted_paths]
- **business outcome:** [clear_goal]
- **acceptance tests:** [test_criteria]
- **commit/PR requirement:** [draft/ready, specific evidence]
- **fallback action:** [what to do if blocked]
- **stop conditions:** [when to halt autonomous looping]
- **output schema:** [expected markdown/json format]

## Historical Directions
*(Note: Obsolete sequencing and assumptions regarding Phase 1 cockpit reports, legacy CompanyOS manual steps, and specific CJ validation prompts are preserved in historical commits but do not govern the current high-throughput merge train.)*
