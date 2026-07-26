from setuptools import setup, find_packages

setup(
    name="intellifile",
    version="2.2.0",
    description="تطبيق إدارة الملفات الذكي المحلي — Hybrid Search + Smart Tags + File Copilot + NER",
    author="Dr. Abdulmalek",
    packages=find_packages(),
    python_requires=">=3.9",
    install_requires=[
        # واجهة المستخدم
        "pyside6>=6.6.0",

        # تحليل الملفات
        "magika>=0.5.0",
        "httpx>=0.24.0",
        "Pillow>=10.0.0",
        "python-magic>=0.4.27",

        # الذكاء الاصطناعي ومعالجة اللغة
        "ollama>=0.1.0",
        "chromadb>=0.4.0",
        "langchain>=0.2.0",
        "sentence-transformers>=2.2.0",
        "numpy>=1.24.0",
        "scipy>=1.10.0",
        "rank-bm25>=0.2.2",

        # خادم API
        "fastapi>=0.104.0",
        "uvicorn[standard]>=0.24.0",
        "python-multipart>=0.0.6",
        "websockets>=12.0",

        # الرسوم البيانية والعلاقات
        "networkx>=3.1",

        # المراقبة والجدولة
        "watchdog>=3.0.0",
        "apscheduler>=3.10.0",

        # معالجة المستندات
        "pdfplumber>=0.10.0",
        "python-docx>=1.0.0",
        "openpyxl>=3.1.2",
        "python-pptx>=0.6.21",

        # أدوات مساعدة
        "pydantic>=2.0.0",
        "rich>=13.0.0",
        "rapidfuzz>=3.0.0",
    ],
    extras_require={
        "voice": [
            "pyttsx3>=2.90",
            "SpeechRecognition>=3.10.0",
            "pyaudio>=0.2.12",
        ],
        "ocr": [
            "pytesseract>=0.3.10",
            "paddleocr>=2.7.0",
            "paddlepaddle>=2.5.0",
        ],
        "whisper": [
            "openai-whisper>=20230314",
        ],
        "extras": [
            "plotly>=5.18.0",
            "pandas>=2.0.0",
        ],
        "all": [
            "pyttsx3>=2.90",
            "SpeechRecognition>=3.10.0",
            "pyaudio>=0.2.12",
            "pytesseract>=0.3.10",
            "paddleocr>=2.7.0",
            "paddlepaddle>=2.5.0",
            "openai-whisper>=20230314",
            "plotly>=5.18.0",
            "pandas>=2.0.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "intellifile=src.main:main",
            "intellifile-cli=cli:main",
        ],
    },
)
