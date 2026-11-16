"""python -m tools.gen_docs  → sinh docs/FEATURE_CATALOG.md và docs/FRAUD_TAXONOMY.md từ mã nguồn (nguồn duy nhất)."""
import os

from agentmon import cardmodel, catalog, criteria, fraud_types, riskregister

D = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
if __name__ == "__main__":
    os.makedirs(D, exist_ok=True)
    for name, text in (("FEATURE_CATALOG.md", catalog.markdown()), ("FRAUD_TAXONOMY.md", fraud_types.markdown()), ("CARD_TAXONOMY.md", cardmodel.markdown()), ("RISK_REGISTER.md", riskregister.markdown()), ("CRITERIA.md", criteria.markdown())):
        with open(os.path.join(D, name), "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print("wrote", name)
