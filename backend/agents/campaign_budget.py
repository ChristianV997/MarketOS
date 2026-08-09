"""DEPRECATED — no production call sites. Budget allocation is unified in
backend.decision.capital_policy (mean-variance QP with adaptive risk
parameters); this ad hoc ±10% ROAS ratchet is retained only for import
compatibility and will be removed.
"""
from collections import defaultdict

class CampaignBudgetAllocator:

    def __init__(self):
        self.budgets = defaultdict(lambda: 1.0)
        self.min_budget = 0.1
        self.max_budget = 10.0
        self.exploration_ratio = 0.1

    def update(self, campaign_id, roas):
        if not campaign_id:
            return

        current = self.budgets[campaign_id]

        if roas > 1.2:
            current *= 1.1
        elif roas < 0.8:
            current *= 0.9

        self.budgets[campaign_id] = min(self.max_budget, max(self.min_budget, current))

    def get_budget(self, campaign_id):
        return self.budgets.get(campaign_id, 1.0)

    def top_campaigns(self):
        return sorted(self.budgets.items(), key=lambda x: x[1], reverse=True)


campaign_budget_allocator = CampaignBudgetAllocator()
