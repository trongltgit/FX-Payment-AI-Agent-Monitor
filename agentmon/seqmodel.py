"""MÔ HÌNH CHUỖI HÀNH VI (Markov bậc 1) theo từng khách: độ "bất ngờ" của bước chuyển (loại giao dịch | kênh | nhóm MCC) so với lịch sử.
Không cần huấn luyện trước – học trực tiếp từ lịch sử khách mỗi lần chấm điểm (cần ≥ 20 giao dịch)."""
import math
from collections import Counter

MIN_HISTORY = 20


def token(h: dict) -> str:
    return f"{h.get('kind')}|{h.get('channel_type') or '-'}|{(str(h.get('mcc') or '')[:2]) or '-'}"


def surprise(hist: list, a: dict):
    """Trả độ bất ngờ chuẩn hóa 0–1 của bước chuyển (giao dịch gần nhất → giao dịch hiện tại); None nếu lịch sử ngắn."""
    if len(hist) < MIN_HISTORY:
        return None
    seq = [token(h) for h in reversed(hist)]              # hist: mới → cũ ; đảo thành cũ → mới
    bigr, uni = Counter(), Counter()
    for p, n in zip(seq, seq[1:]):
        bigr[(p, n)] += 1
        uni[p] += 1
    V = len(set(seq)) + 1
    prev, cur = seq[-1], token(a)
    p = (bigr[(prev, cur)] + 1.0) / (uni[prev] + V)       # làm trơn Laplace
    return min(1.0, -math.log(p) / math.log(V + 1) / 1.6)
