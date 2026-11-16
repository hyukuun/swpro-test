"""
획 데이터용 한글 지식 (폰트 무관): 음절 분해, 글자 집합, 자모 구성(부품·획 수), 획순 템플릿
추출(extract.py)·조합(compose.py)·편집기(editor.py)·scripts/ 검수 스크립트가 이 파일을 쓴다

app/core/hangul.py(서버 판정용 음절 분해·조합, Syllable 형식)와는 따로다.
여기 decompose()는 [("cho", "ㄷ"), ("jung", "ㅝ"), ("jong", "ㅇ")] 목록을 돌려준다.
"""

CHO = list("ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ")
JUNG = list("ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ")
JONG = [""] + list("ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ")

# ───────── 획순 템플릿 ─────────
# 바깥 리스트 = 획 순서, 안쪽 = 그 획 안의 방향 단계, "A|B" = 둘 중 하나
# 끝에 "!" = 선분 하나만 (갈림점을 지나 이어지지 않음, 예: ㅊ·ㅎ 꼭지)
SIOT = [["S|SW", "SW|W"], ["SE|E"]]  # ㅅ: (꼭지 ↓ 후) 왼쪽 다리 / 오른쪽 다리

BASE = {
    # 자음
    "ㄱ": [["E", "S|SW"]],
    "ㄴ": [["S", "E"]],
    "ㄷ": [["E"], ["S", "E"]],
    "ㄹ": [["E", "S"], ["E"], ["S", "E"]],
    "ㅁ": [["S"], ["E", "S"], ["E"]],
    "ㅂ": [["S"], ["S"], ["E"], ["E"]],
    "ㅅ": SIOT,
    "ㅇ": [["CCW"]],
    "ㅈ": [["E"]] + SIOT,  # Noto 모양 기준 3획 (ㅡ + ㅅ)
    "ㅊ": [["S|E!"], ["E"]] + SIOT,  # 꼭지 + ㅡ + ㅅ
    "ㅋ": [["E", "S|SW"], ["E"]],
    "ㅌ": [["E"], ["E"], ["S", "E"]],
    "ㅍ": [["E"], ["S|SE"], ["S|SW"], ["E"]],
    "ㅎ": [["S|E!"], ["E"], ["CCW"]],
    # 모음
    "ㅏ": [["S"], ["E"]],
    "ㅐ": [["S"], ["E"], ["S"]],
    "ㅑ": [["S"], ["E"], ["E"]],
    "ㅒ": [["S"], ["E"], ["E"], ["S"]],
    "ㅓ": [["E"], ["S"]],
    "ㅔ": [["E"], ["S"], ["S"]],
    "ㅕ": [["E"], ["E"], ["S"]],
    "ㅖ": [["E"], ["E"], ["S"], ["S"]],
    "ㅗ": [["S"], ["E"]],
    "ㅛ": [["S"], ["S"], ["E"]],
    "ㅜ": [["E"], ["S"]],
    "ㅠ": [["E"], ["S"], ["S"]],
    "ㅡ": [["E"]],
    "ㅣ": [["S"]],
}
# 쌍자음·겹받침·복합모음 = 부품 이어붙이기 (앞 부품이 먼저, 왼쪽)
COMPOSE = {
    "ㄲ": "ㄱㄱ",
    "ㄸ": "ㄷㄷ",
    "ㅃ": "ㅂㅂ",
    "ㅆ": "ㅅㅅ",
    "ㅉ": "ㅈㅈ",
    "ㄳ": "ㄱㅅ",
    "ㄵ": "ㄴㅈ",
    "ㄶ": "ㄴㅎ",
    "ㄺ": "ㄹㄱ",
    "ㄻ": "ㄹㅁ",
    "ㄼ": "ㄹㅂ",
    "ㄽ": "ㄹㅅ",
    "ㄾ": "ㄹㅌ",
    "ㄿ": "ㄹㅍ",
    "ㅀ": "ㄹㅎ",
    "ㅄ": "ㅂㅅ",
    "ㅘ": "ㅗㅏ",
    "ㅙ": "ㅗㅐ",
    "ㅚ": "ㅗㅣ",
    "ㅝ": "ㅜㅓ",
    "ㅞ": "ㅜㅔ",
    "ㅟ": "ㅜㅣ",
    "ㅢ": "ㅡㅣ",
}
PIECES = {j: list(COMPOSE.get(j, j)) for j in list(BASE) + list(COMPOSE)}
JAMO_TEMPLATES = {j: [d for p in PIECES[j] for d in BASE[p]] for j in PIECES}  # 자모 51개
STROKE_COUNT = {j: len(v) for j, v in BASE.items()}  # 기본 자모 획 수 (ㅈ 3획, ㅊ 4획 — Noto 모양 기준)
V_VOWELS = set("ㅏㅐㅑㅒㅓㅔㅕㅖㅣ")  # 세로 모음
H_VOWELS = set("ㅗㅛㅜㅠㅡ")  # 가로 모음 (나머지 = 복합)


def decompose(syl):
    """'뒁' → [("cho", "ㄷ"), ("jung", "ㅝ"), ("jong", "ㅇ")]"""
    code = ord(syl) - 0xAC00
    cho, jung, jong = code // 588, (code % 588) // 28, code % 28
    parts = [("cho", CHO[cho]), ("jung", JUNG[jung])]
    if jong:
        parts.append(("jong", JONG[jong]))
    return parts


def piece_sizes(jamo):
    """부품별 획 수 (ㅘ → [2, 2], ㄱ → [1])"""
    return [STROKE_COUNT[p] for p in COMPOSE.get(jamo, jamo)]


def vowel_dir(v):
    """모음방향: V 세로 / H 가로 / C 복합"""
    return "V" if v in V_VOWELS else "H" if v in H_VOWELS else "C"


def ksx1001():
    """완성형 2,350자 (EUC-KR 0xB0A1 ~ 0xC8FE)"""
    return [bytes([hi, lo]).decode("euc-kr") for hi in range(0xB0, 0xC9) for lo in range(0xA1, 0xFF)]


def all_syllables():
    """현대 한글 11,172자"""
    return [chr(c) for c in range(0xAC00, 0xD7A4)]


def jamo_entries(jamo, role):
    """자모 → 획 목록. unit = 부품 구분 (ㄼ이면 jong0 = ㄹ, jong1 = ㅂ)"""
    multi = len(PIECES[jamo]) > 1
    return [
        {"jamo": jamo, "role": role, "unit": f"{role}{pi}", "piece": pi, "multi": multi, "dirs": dirs}
        for pi, base in enumerate(PIECES[jamo])
        for dirs in BASE[base]
    ]


def syllable_template(syl):
    """음절 → 초·중·종 자모 획 목록을 이어붙인 것"""
    return [e for role, jamo in decompose(syl) for e in jamo_entries(jamo, role)]
