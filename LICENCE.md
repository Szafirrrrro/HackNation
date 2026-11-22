# Komponenty, licencje i usługi

Wykaz komponentów zewnętrznych ScamGraph i warunków ich użycia (wymóg pkt 4 zadania NASK). Nie jest to licencja na kod zespołu: prawa do niego reguluje §4 regulaminu zadania. Przy dystrybucji należy zachować noty licencyjne pakietów i ich składników.

Klucze API nie są wymagane.

## Aplikacja

| Komponent | Zastosowanie | Licencja |
| --- | --- | --- |
| CPython | interpreter | PSF |
| Streamlit | panel analityka | Apache-2.0 |
| pyvis | graf | BSD-3-Clause |
| vis-network | graf w przeglądarce | Apache-2.0 lub MIT |
| Plotly | oś czasu | MIT |
| pandas | tabele | BSD-3-Clause |
| NumPy | obliczenia | BSD-3-Clause, składniki także 0BSD, MIT, Zlib, CC0-1.0 |
| SciPy, scikit-learn | obliczenia, n-gramy | BSD-3-Clause |
| Pillow | obraz | MIT-CMU |
| ImageHash | pHash, dHash | BSD-2-Clause |
| PyWavelets | zależność ImageHash | MIT i BSD-3-Clause |
| Playwright | sterowanie przeglądarką | Apache-2.0 |
| urllib3 | HTTP | MIT |
| certifi | certyfikaty | MPL-2.0 |
| idna | nazwy domen | BSD-3-Clause |
| tinycss2 | CSS | BSD-3-Clause |
| tldextract | domeny | BSD-3-Clause |
| publicsuffixlist, dane Public Suffix List | sufiksy domen | MPL-2.0 |
| Tesseract, tessdata | OCR | Apache-2.0 |

## Usługi opcjonalne

| Komponent | Zastosowanie | Licencja |
| --- | --- | --- |
| PostgreSQL, pgvector | karty i historia przebiegów | PostgreSQL License |
| psycopg, psycopg-binary | sterownik PostgreSQL | LGPL-3.0 |
| Neo4j Community | eksport grafu | GPLv3 |
| Sterownik Neo4j dla Pythona | eksport grafu | Apache-2.0 i Python-2.0 |

## Laboratorium modeli: biblioteki

| Komponent | Licencja |
| --- | --- |
| PyTorch, torchvision, torchaudio | BSD |
| transformers, huggingface_hub, sentence-transformers, safetensors, sentencepiece | Apache-2.0 |
| SpeechBrain, pytesseract, OpenCV, TensorBoard, efficientnet_pytorch | Apache-2.0 |
| faster-whisper, ONNX Runtime, PyYAML, loralib, imutils | MIT |
| InsightFace (sam pakiet, bez wag buffalo_l) | MIT |
| protobuf, psutil, scikit-image | BSD-3-Clause |
| tqdm | MPL-2.0 i MIT |
| dlib | Boost Software License |
| Chromaprint | LGPL-2.1 |

## Modele i wagi

Licencje według deklaracji w `models/containers/*/models.py`. Przed dystrybucją wag należy je potwierdzić u producenta.

| Model | Zadanie | Tryb | Licencja |
| --- | --- | --- | --- |
| CLIP ViT-B/32 | podobieństwo obrazu | domyślny | MIT |
| Whisper small | mowa | domyślny | MIT |
| Whisper base | mowa | na żądanie | MIT |
| ECAPA (SpeechBrain) | głos | na żądanie | Apache-2.0 |
| multilingual-e5-small | tekst | na żądanie | MIT |
| mDeBERTa-v3 XNLI | temat | na żądanie | MIT |
| OWLv2 | obiekty | na żądanie | Apache-2.0 |
| YuNet | detekcja twarzy | na żądanie | MIT |
| SFace | embedding twarzy | na żądanie | Apache-2.0 |
| Effort (kod i wagi) | pochodzenie obrazu | na żądanie | **CC BY-NC 4.0, tylko użycie niekomercyjne, z uznaniem autorstwa** |
| CLIP ViT-L/14 | składnik Effort | na żądanie | MIT |

## Dane i usługi zewnętrzne

| Źródło | Warunki |
| --- | --- |
| Google Chrome | warunki Google, produkt binarny pobierany przy budowie obrazu |
| Windows.Media.Ocr | składnik systemu Windows |
| Biblioteka reklam Meta | warunki Meta, tryb live wymaga zadeklarowania uprawnienia operatora |
| Tranco | warunki list składowych: możliwa atrybucja, udostępnianie na tych samych zasadach i zakaz użycia komercyjnego. Cytowanie: Le Pochat i in., NDSS 2019 |
| Lista CERT (opcjonalna) | dostarcza operator, zgodnie z warunkami źródła |
| Materiały NASK | tylko na potrzeby wyzwania, zakaz publicznego rozpowszechniania |

Szczegóły: [docs/KOMPONENTY.md](docs/KOMPONENTY.md), [models/README.md](models/README.md).
