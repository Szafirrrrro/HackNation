import easyocr

easyocr.Reader(["pl", "en"], gpu=False, model_storage_directory="/models/easyocr",
               download_enabled=True)
