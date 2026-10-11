import { APPROVAL_LEDGER_REPORT_VERSION } from "../contracts/approvalLedger.ts";

/** Mirrored offline CLI artifact: companyos-approval-ledger-v1 (sanitized seed + evidence refs). */
const FIXTURE = {
  "approval_count": 2,
  "approved_count": 0,
  "audit_events": [
    {
      "actor": "operator",
      "after_status": "draft",
      "approval_id": "seed-manual-import",
      "before_status": "none",
      "event_id": "audit-seed-manual-import",
      "event_type": "approval_request_created",
      "evidence_refs": [],
      "immutable_note": "Offline audit record; no external action occurred.",
      "reason": "Deterministic offline request assessment.",
      "timestamp": "offline-deterministic"
    },
    {
      "actor": "operator",
      "after_status": "blocked_by_policy",
      "approval_id": "seed-publish",
      "before_status": "none",
      "event_id": "audit-seed-publish",
      "event_type": "approval_request_created",
      "evidence_refs": [],
      "immutable_note": "Offline audit record; no external action occurred.",
      "reason": "Deterministic offline request assessment.",
      "timestamp": "offline-deterministic"
    }
  ],
  "blocked_count": 1,
  "critical_count": 0,
  "decisions": [],
  "denied_count": 0,
  "expired_count": 0,
  "expiries": [
    {
      "created_at": "offline-deterministic",
      "expired": false,
      "expires_at": "offline-deterministic-expiry",
      "reason": ""
    },
    {
      "created_at": "offline-deterministic",
      "expired": false,
      "expires_at": "offline-deterministic-expiry",
      "reason": ""
    }
  ],
  "generated_at": "offline-deterministic",
  "highest_risk_requests": [
    {
      "action_category": "site_publish",
      "approval_id": "seed-publish",
      "conditions": [
        {
          "condition_id": "condition-1",
          "description": "copy approved",
          "evidence_ref": "operator_input",
          "required": true,
          "satisfied": true
        },
        {
          "condition_id": "condition-2",
          "description": "claims approved",
          "evidence_ref": "operator_input",
          "required": true,
          "satisfied": true
        },
        {
          "condition_id": "condition-3",
          "description": "policies approved",
          "evidence_ref": "operator_input",
          "required": true,
          "satisfied": true
        },
        {
          "condition_id": "condition-4",
          "description": "deployment reviewed",
          "evidence_ref": "operator_input",
          "required": true,
          "satisfied": true
        }
      ],
      "created_at": "offline-deterministic",
      "evidence": [],
      "expires_at": "offline-deterministic-expiry",
      "external_action_performed": false,
      "external_system": "none",
      "linked_model_route_id": "",
      "linked_skill_id": "",
      "linked_tool_id": "",
      "linked_workflow_id": "",
      "mutated": false,
      "network_calls": false,
      "owner_department": "risk_approval",
      "read_only": true,
      "request_title": "Publish launch draft",
      "request_type": "site_publish",
      "requested_budget_cap": {
        "consumed": 0,
        "currency": "USD",
        "monthly": 0,
        "per_run": 0,
        "remaining": 0,
        "scope": "site publish"
      },
      "requested_by_agent": "operator",
      "requested_mode": "approval_required",
      "requested_scope": {
        "actions": [
          "site_publish"
        ],
        "constraints": [
          "no external execution"
        ],
        "environments": [
          "offline"
        ],
        "expiry_required": true,
        "resources": [
          "offline-draft"
        ]
      },
      "requested_time_window": {
        "created_at": "offline-deterministic",
        "expired": false,
        "expires_at": "offline-deterministic-expiry",
        "reason": ""
      },
      "required_approver_role": "site_owner",
      "risk_level": "high",
      "side_effect_type": "none",
      "status": "blocked_by_policy",
      "target_resource": "offline-draft"
    },
    {
      "action_category": "web_data_acquisition",
      "approval_id": "seed-manual-import",
      "conditions": [
        {
          "condition_id": "condition-1",
          "description": "source is public or manual",
          "evidence_ref": "operator_input",
          "required": true,
          "satisfied": true
        },
        {
          "condition_id": "condition-2",
          "description": "robots/TOS review complete",
          "evidence_ref": "operator_input",
          "required": true,
          "satisfied": true
        }
      ],
      "created_at": "offline-deterministic",
      "evidence": [],
      "expires_at": "offline-deterministic-expiry",
      "external_action_performed": false,
      "external_system": "none",
      "linked_model_route_id": "",
      "linked_skill_id": "",
      "linked_tool_id": "",
      "linked_workflow_id": "",
      "mutated": false,
      "network_calls": false,
      "owner_department": "risk_approval",
      "read_only": true,
      "request_title": "Review sanitized import",
      "request_type": "web_data_acquisition",
      "requested_budget_cap": {
        "consumed": 0,
        "currency": "USD",
        "monthly": 0,
        "per_run": 0,
        "remaining": 0,
        "scope": "web acquisition"
      },
      "requested_by_agent": "operator",
      "requested_mode": "draft_only",
      "requested_scope": {
        "actions": [
          "web_data_acquisition"
        ],
        "constraints": [
          "no external execution"
        ],
        "environments": [
          "offline"
        ],
        "expiry_required": true,
        "resources": [
          "offline-draft"
        ]
      },
      "requested_time_window": {
        "created_at": "offline-deterministic",
        "expired": false,
        "expires_at": "offline-deterministic-expiry",
        "reason": ""
      },
      "required_approver_role": "human_operator",
      "risk_level": "medium",
      "side_effect_type": "none",
      "status": "draft",
      "target_resource": "offline-draft"
    }
  ],
  "next_best_action": "Review blocked and pending requests; keep external-world actions disabled until a future credential, policy, and human-approval implementation is explicitly reviewed.",
  "pending_count": 0,
  "policies": [
    {
      "blocked_in_current_mode": false,
      "budget_cap": {
        "consumed": 0,
        "currency": "USD",
        "monthly": 100,
        "per_run": 5,
        "remaining": 100,
        "scope": "model route"
      },
      "decision_class": "approval_possible_later",
      "default_risk": "medium",
      "policy_id": "approval-policy-model_spend",
      "rationale": "Local and cheap routes can be simulated; no model call is made.",
      "request_type": "model_spend",
      "required_approver_role": "human_operator",
      "required_conditions": [
        "model route is registered",
        "run is within budget cap"
      ]
    },
    {
      "blocked_in_current_mode": false,
      "budget_cap": {
        "consumed": 0,
        "currency": "USD",
        "monthly": 0,
        "per_run": 0,
        "remaining": 0,
        "scope": "web acquisition"
      },
      "decision_class": "approval_possible_later",
      "default_risk": "medium",
      "policy_id": "approval-policy-web_data_acquisition",
      "rationale": "Manual imports are safe drafts; network acquisition needs later approval.",
      "request_type": "web_data_acquisition",
      "required_approver_role": "human_operator",
      "required_conditions": [
        "source is public or manual",
        "robots/TOS review complete"
      ]
    },
    {
      "blocked_in_current_mode": true,
      "budget_cap": {
        "consumed": 0,
        "currency": "USD",
        "monthly": 0,
        "per_run": 0,
        "remaining": 0,
        "scope": "outreach"
      },
      "decision_class": "blocked_in_current_mode",
      "default_risk": "high",
      "policy_id": "approval-policy-email_send",
      "rationale": "Email is draft-only and cannot be sent.",
      "request_type": "email_send",
      "required_approver_role": "human_operator",
      "required_conditions": [
        "recipient consent verified",
        "do-not-contact is false",
        "message approved",
        "unsubscribe language present"
      ]
    },
    {
      "blocked_in_current_mode": true,
      "budget_cap": {
        "consumed": 0,
        "currency": "USD",
        "monthly": 0,
        "per_run": 0,
        "remaining": 0,
        "scope": "payment"
      },
      "decision_class": "blocked_in_current_mode",
      "default_risk": "critical",
      "policy_id": "approval-policy-payment_creation",
      "rationale": "Payment creation is permanently blocked in this version.",
      "request_type": "payment_creation",
      "required_approver_role": "finance_manager",
      "required_conditions": [
        "payee verified",
        "payment purpose approved",
        "dual review complete"
      ]
    },
    {
      "blocked_in_current_mode": true,
      "budget_cap": {
        "consumed": 0,
        "currency": "USD",
        "monthly": 0,
        "per_run": 0,
        "remaining": 0,
        "scope": "ad launch"
      },
      "decision_class": "blocked_in_current_mode",
      "default_risk": "critical",
      "policy_id": "approval-policy-ad_launch",
      "rationale": "Ad launch is not available.",
      "request_type": "ad_launch",
      "required_approver_role": "marketing_manager",
      "required_conditions": [
        "creative approved",
        "budget cap approved",
        "claims review passed",
        "tracking plan approved"
      ]
    },
    {
      "blocked_in_current_mode": true,
      "budget_cap": {
        "consumed": 0,
        "currency": "USD",
        "monthly": 0,
        "per_run": 0,
        "remaining": 0,
        "scope": "site publish"
      },
      "decision_class": "blocked_in_current_mode",
      "default_risk": "high",
      "policy_id": "approval-policy-site_publish",
      "rationale": "Site publishing is blocked in current mode; payloads remain draft-only.",
      "request_type": "site_publish",
      "required_approver_role": "site_owner",
      "required_conditions": [
        "copy approved",
        "claims approved",
        "policies approved",
        "deployment reviewed"
      ]
    }
  ],
  "queue_summary": {
    "approved": 0,
    "blocked": 1,
    "denied": 0,
    "draft_or_simulated": 1,
    "expired": 0,
    "high_risk": 1,
    "missing_conditions": 0,
    "pending": 0,
    "revoked": 0
  },
  "report_version": "companyos-approval-ledger-v1",
  "requests": [
    {
      "action_category": "web_data_acquisition",
      "approval_id": "seed-manual-import",
      "conditions": [
        {
          "condition_id": "condition-1",
          "description": "source is public or manual",
          "evidence_ref": "ev-manual-import-1",
          "required": true,
          "satisfied": true
        },
        {
          "condition_id": "condition-2",
          "description": "robots/TOS review complete",
          "evidence_ref": "operator_input",
          "required": true,
          "satisfied": true
        }
      ],
      "created_at": "offline-deterministic",
      "evidence": [
        {
          "evidence_type": "sanitized_fixture",
          "ref_id": "ev-manual-import-1",
          "sanitized": true,
          "source": "tests/fixtures/companyos_approval/approval_requests_seed.json",
          "summary": "Sanitized offline import packet for policy review only."
        }
      ],
      "expires_at": "offline-deterministic-expiry",
      "external_action_performed": false,
      "external_system": "none",
      "linked_model_route_id": "",
      "linked_skill_id": "",
      "linked_tool_id": "",
      "linked_workflow_id": "",
      "mutated": false,
      "network_calls": false,
      "owner_department": "risk_approval",
      "read_only": true,
      "request_title": "Review sanitized import",
      "request_type": "web_data_acquisition",
      "requested_budget_cap": {
        "consumed": 0,
        "currency": "USD",
        "monthly": 0,
        "per_run": 0,
        "remaining": 0,
        "scope": "web acquisition"
      },
      "requested_by_agent": "operator",
      "requested_mode": "draft_only",
      "requested_scope": {
        "actions": [
          "web_data_acquisition"
        ],
        "constraints": [
          "no external execution"
        ],
        "environments": [
          "offline"
        ],
        "expiry_required": true,
        "resources": [
          "offline-draft"
        ]
      },
      "requested_time_window": {
        "created_at": "offline-deterministic",
        "expired": false,
        "expires_at": "offline-deterministic-expiry",
        "reason": ""
      },
      "required_approver_role": "human_operator",
      "risk_level": "medium",
      "side_effect_type": "none",
      "status": "draft",
      "target_resource": "offline-draft"
    },
    {
      "action_category": "site_publish",
      "approval_id": "seed-publish",
      "conditions": [
        {
          "condition_id": "condition-1",
          "description": "copy approved",
          "evidence_ref": "operator_input",
          "required": true,
          "satisfied": true
        },
        {
          "condition_id": "condition-2",
          "description": "claims approved",
          "evidence_ref": "operator_input",
          "required": true,
          "satisfied": true
        },
        {
          "condition_id": "condition-3",
          "description": "policies approved",
          "evidence_ref": "operator_input",
          "required": true,
          "satisfied": true
        },
        {
          "condition_id": "condition-4",
          "description": "deployment reviewed",
          "evidence_ref": "operator_input",
          "required": true,
          "satisfied": true
        }
      ],
      "created_at": "offline-deterministic",
      "evidence": [
        {
          "evidence_type": "policy_blocker",
          "ref_id": "ev-publish-block-1",
          "sanitized": true,
          "source": "companyos-approval-ledger-v1",
          "summary": "Site publish remains blocked in current offline mode."
        }
      ],
      "expires_at": "offline-deterministic-expiry",
      "external_action_performed": false,
      "external_system": "none",
      "linked_model_route_id": "",
      "linked_skill_id": "",
      "linked_tool_id": "",
      "linked_workflow_id": "",
      "mutated": false,
      "network_calls": false,
      "owner_department": "risk_approval",
      "read_only": true,
      "request_title": "Publish launch draft",
      "request_type": "site_publish",
      "requested_budget_cap": {
        "consumed": 0,
        "currency": "USD",
        "monthly": 0,
        "per_run": 0,
        "remaining": 0,
        "scope": "site publish"
      },
      "requested_by_agent": "operator",
      "requested_mode": "approval_required",
      "requested_scope": {
        "actions": [
          "site_publish"
        ],
        "constraints": [
          "no external execution"
        ],
        "environments": [
          "offline"
        ],
        "expiry_required": true,
        "resources": [
          "offline-draft"
        ]
      },
      "requested_time_window": {
        "created_at": "offline-deterministic",
        "expired": false,
        "expires_at": "offline-deterministic-expiry",
        "reason": ""
      },
      "required_approver_role": "site_owner",
      "risk_level": "high",
      "side_effect_type": "none",
      "status": "blocked_by_policy",
      "target_resource": "offline-draft"
    }
  ],
  "revocations": [],
  "revoked_count": 0,
  "safety_summary": {
    "audit_trail_present": true,
    "credentials_present": false,
    "external_action_performed": false,
    "live_capabilities_enabled": false,
    "mutated": false,
    "network_calls": false,
    "policy_fail_closed": true,
    "read_only": true,
    "secrets_stored": false,
    "summary": "Offline ledger only; records and simulations do not authorize execution."
  },
  "simulations": [
    {
      "action": "model_spend",
      "audit_event_type": "companyos_approval_simulation_model_spend",
      "blocking_reasons": [],
      "budget_cap": {
        "consumed": 0,
        "currency": "USD",
        "monthly": 100,
        "per_run": 5,
        "remaining": 100,
        "scope": "model route"
      },
      "can_be_approved_now": true,
      "missing_conditions": [],
      "request": {
        "action_category": "model_spend",
        "approval_id": "simulation-model_spend",
        "conditions": [
          {
            "condition_id": "condition-1",
            "description": "model route is registered",
            "evidence_ref": "operator_input",
            "required": true,
            "satisfied": true
          },
          {
            "condition_id": "condition-2",
            "description": "run is within budget cap",
            "evidence_ref": "operator_input",
            "required": true,
            "satisfied": true
          }
        ],
        "created_at": "offline-deterministic",
        "evidence": [],
        "expires_at": "offline-deterministic-expiry",
        "external_action_performed": false,
        "external_system": "none",
        "linked_model_route_id": "",
        "linked_skill_id": "",
        "linked_tool_id": "",
        "linked_workflow_id": "",
        "mutated": false,
        "network_calls": false,
        "owner_department": "risk_approval",
        "read_only": true,
        "request_title": "Simulate model_spend",
        "request_type": "model_spend",
        "requested_budget_cap": {
          "consumed": 0,
          "currency": "USD",
          "monthly": 100,
          "per_run": 0.2,
          "remaining": 100,
          "scope": "model route"
        },
        "requested_by_agent": "approval-gatekeeper",
        "requested_mode": "simulation",
        "requested_scope": {
          "actions": [
            "model_spend"
          ],
          "constraints": [
            "no external execution"
          ],
          "environments": [
            "offline"
          ],
          "expiry_required": true,
          "resources": [
            "offline-draft"
          ]
        },
        "requested_time_window": {
          "created_at": "offline-deterministic",
          "expired": false,
          "expires_at": "offline-deterministic-expiry",
          "reason": ""
        },
        "required_approver_role": "human_operator",
        "risk_level": "medium",
        "side_effect_type": "none",
        "status": "simulated",
        "target_resource": "offline-draft"
      },
      "request_type": "model_spend",
      "result": "would_auto_allow_draft",
      "simulation_id": "simulation-model_spend"
    }
  ]
} as const;

export function buildApprovalLedgerFixture(): Record<string, unknown> {
  if (FIXTURE.report_version !== APPROVAL_LEDGER_REPORT_VERSION) {
    throw new Error("fixture_version_mismatch");
  }
  return structuredClone(FIXTURE) as unknown as Record<string, unknown>;
}
