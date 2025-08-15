# Generic Goal Tracking Commands for AI Agents

This document describes a generic command system for AI agents to track and execute complex multi-phase initiatives.

## Command Overview

### `/project:ceph-bootstrap-review`

**Purpose**: Review current status and determine next actions for the Ceph bootstrap initiative

**Key Actions**:
1. Read all documentation in `/docs/ceph/bootstrap/`
2. Parse `goals.json` to understand current phase and objective status
3. Check actual cluster state against expected deliverables
4. Identify blocking issues or unmet prerequisites
5. Generate comprehensive status report with next steps

**Parameters**: None required

**Example Output**:
```markdown
## Ceph Bootstrap Status Review

**Current Phase**: Phase 0 - Pre-Implementation Monitoring
**Status**: Active (Monitoring trigger conditions)

### Trigger Conditions Check:
- Storage Usage: 11Gi / 100Gi ❌
- Production Workloads: No ❌
- RWX Required: No ❌
- S3 Required: No ❌

**Recommendation**: Continue monitoring. No triggers met yet.

### Next Objective When Triggered:
- Objective 0.2: Backup Current State
- Required Actions:
  1. Create full PVC backup
  2. Test restoration process
  3. Document storage inventory
```

### `/project:ceph-bootstrap-execute`

**Purpose**: Execute the next pending objective in the Ceph bootstrap process

**Key Actions**:
1. Identify current objective from `goals.json`
2. Gather relevant context (search codebase, check examples)
3. Request user input for external examples if needed
4. Execute required deliverables
5. Update goal status and create artifacts
6. Validate completion criteria

**Parameters**: Optional objective ID to execute specific task (e.g., "1.2")

**Execution Flow**:
```
1. Pre-execution:
   - Verify prerequisites are met
   - Search for relevant patterns in codebase
   - Check documentation for guidelines

2. During execution:
   - Create/modify files as needed
   - Run validation commands
   - Document decisions and rationale

3. Post-execution:
   - Update goals.json status
   - Create required artifacts
   - Run validation checks
   - Prepare for next objective
```

## Generic Goal Tracking System

### Structure

The `goals.json` file provides a structured way to track complex initiatives:

```json
{
  "initiative": {
    "name": "Project Name",
    "status": "pending|active|completed",
    "trigger_conditions": { /* Optional triggers */ }
  },
  "phases": [
    {
      "id": "phase-1",
      "name": "Phase Name",
      "status": "pending|active|completed",
      "prerequisites": ["phase-0"],
      "objectives": [
        {
          "id": "1.1",
          "name": "Objective Name",
          "status": "pending|in_progress|completed|blocked",
          "deliverables": [],
          "validation": "How to verify completion",
          "artifacts": { /* Files/directories created */ }
        }
      ]
    }
  ]
}
```

### Status Definitions

**Initiative Status**:
- `pending`: Waiting for trigger conditions
- `active`: Currently being worked on
- `completed`: All phases complete

**Phase Status**:
- `pending`: Prerequisites not met
- `active`: At least one objective in progress
- `completed`: All objectives complete

**Objective Status**:
- `pending`: Not started
- `in_progress`: Currently being worked on
- `completed`: Deliverables complete and validated
- `blocked`: Cannot proceed due to external factors

### Command Behaviors

**Review Command**:
- Always reads latest documentation
- Checks real cluster state vs expected
- Identifies gaps and blockers
- Provides actionable recommendations

**Execute Command**:
- Only works on one objective at a time
- Automatically searches for context
- Asks user for examples when needed
- Updates tracking data after completion
- Validates before marking complete

### Integration with Existing Tools

The commands integrate with:
- GitOps workflows (creating PRs)
- Monitoring scripts (validation)
- Documentation (updating progress)
- External resources (web search, examples)

### Example Interaction Flow

```
User: /project:ceph-bootstrap-review

AI: [Reviews all docs and goals.json]
    "Phase 0 active. No triggers met. Continue monitoring."

[Later, after trigger condition met]

User: /project:ceph-bootstrap-execute

AI: "Trigger detected! Starting Objective 0.2: Backup Current State"
    [Creates backup scripts]
    [Runs backup]
    [Updates goals.json]
    "Backup complete. Ready for Phase 1."

User: /project:ceph-bootstrap-execute

AI: "Starting Objective 1.1: Hardware Validation"
    "I need examples of Talos storage configuration. Please share a link to a repository using Ceph with Talos."

User: [provides link]

AI: [Analyzes example]
    [Creates validation script]
    [Runs checks]
    [Updates status]
    "Hardware validation complete. 3/3 objectives in Phase 1 remaining."
```

## Benefits of This Approach

1. **Systematic Progress**: Clear tracking of what's done and what's next
2. **Context Preservation**: AI agents can pick up where others left off
3. **Automatic Validation**: Each objective has clear success criteria
4. **Flexible Execution**: Can handle triggers, prerequisites, and dependencies
5. **User Collaboration**: Requests specific help when needed
6. **Artifact Creation**: Documents all work for future reference

## Extending to Other Projects

This pattern can be adapted for any multi-phase initiative:

1. Create a `goals.json` in the project directory
2. Define phases and objectives with clear deliverables
3. Use `/project:<name>-review` to check status
4. Use `/project:<name>-execute` to make progress
5. Update commands to reference correct paths and validation

The generic nature allows AI agents to work systematically on complex projects while maintaining context and ensuring quality.