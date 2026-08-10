from .models import CommerceMvpRun
def report_to_dict(run: CommerceMvpRun) -> dict: return run.to_dict()
def report_to_markdown(run: CommerceMvpRun) -> str: return run.to_markdown()
