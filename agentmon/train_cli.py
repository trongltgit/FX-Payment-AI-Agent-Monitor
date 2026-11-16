"""python -m agentmon.train_cli  -> huấn luyện lại 2 mô hình Isolation Forest (FX, PAY)."""
from agentmon import botmodel, fraudgbm, ml

if __name__ == "__main__":
    for d in ("FX", "PAY"):
        print(ml.train(d))
        print(fraudgbm.train(d))
    print(botmodel.train())
