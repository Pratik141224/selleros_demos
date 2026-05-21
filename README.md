# SellerOS — Q&D Demo Suite
## Demo 3: Buyer Persona & Intent Match Scorer
## Demo 4: Title & Bullet A/B Optimizer

---

## Prerequisites
- Python 3.9+
- An Anthropic API key → https://console.anthropic.com

---

## Setup (one-time)

```bash
# 1. Clone / unzip this folder, then:
cd selleros_demos

# 2. Create virtual environment
python -m venv venv

# Windows:
venv\Scripts\activate

# Mac/Linux:
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set your API key
# Windows:
set ANTHROPIC_API_KEY=sk-ant-your-key-here

# Mac/Linux:
export ANTHROPIC_API_KEY=sk-ant-your-key-here
```

---

## Running the demos

### Demo 3 — Buyer Persona & Intent Match Scorer
```bash
cd demo2_persona_scorer
python app.py
# Open: http://localhost:5001
```

### Demo 4 — Title & Bullet A/B Optimizer
```bash
cd demo1_ab_optimizer
python app.py
# Open: http://localhost:5002
```

---

## Project structure
```
selleros_demos/
├── requirements.txt
├── shared/
│   ├── claude_client.py       # Shared Anthropic API wrapper
│   └── prompts.py             # All Claude prompt templates
├── demo2_persona_scorer/
│   ├── app.py                 # Flask app + API routes
│   ├── agents.py              # 2 Claude API call pipeline
│   ├── scorer.py              # Fit scoring logic
│   └── templates/
│       └── index.html         # Full frontend UI
└── demo1_ab_optimizer/
    ├── app.py                 # Flask app + API routes
    ├── agents.py              # 3 Claude API call pipeline
    ├── scorer.py              # Variant scoring logic
    └── templates/
        └── index.html         # Full frontend UI
```

---

## Cost per run
- Demo 3 (Persona Scorer): ~2 Claude API calls ≈ $0.03–0.05
- Demo 4 (A/B Optimizer): ~3 Claude API calls ≈ $0.04–0.07
