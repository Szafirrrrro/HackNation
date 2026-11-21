EMBED = [
    # (hf_id, prefix, licencja, notatka)
    ("intfloat/multilingual-e5-small", "query: ", "MIT", "118M param, 384d, lekki"),
    ("BAAI/bge-m3", "", "MIT", "568M param, 1024d, najmocniejszy wielojęzyczny, 8k ctx"),
]
ZEROSHOT = [
    ("MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli", "MIT", "107M param, szybki"),
    ("MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7", "MIT", "278M param, dokładniejszy"),
]
LABELS = [
    "inwestycje i kryptowaluty", "zdrowie, leki i suplementy", "wygrana, loteria lub nagroda",
    "dopłaty i pomoc od rządu lub banku", "polityka", "zakupy i promocje", "randki i związki",
]
TEMPLATE = "Ten tekst dotyczy: {}."
