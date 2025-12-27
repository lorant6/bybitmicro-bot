#!/bin/bash

# Define paths
BOT_DIR="$HOME/trading_bot"
cd "$BOT_DIR" || { echo "❌ Directory not found!"; exit 1; }

echo "📦 Preparing Trading Bot for GitHub Export..."

# 1. Create .gitignore (THE SAFETY NET)
# This prevents git from ever seeing your keys or system folders
echo "config.py" > .gitignore
echo "venv/" >> .gitignore
echo "__pycache__/" >> .gitignore
echo "*.log" >> .gitignore
echo ".DS_Store" >> .gitignore
echo "✅ .gitignore created (Secure!)"

# 2. Create requirements.txt (Dependency List)
# This allows others to install the bot with 'pip install -r requirements.txt'
venv/bin/pip freeze > requirements.txt
echo "✅ requirements.txt generated"

# 3. Create a Safe Config Template
# We copy your structure but remove the keys
cat <<EOF > config_example.py
# RENAME THIS FILE TO config.py AND ADD YOUR KEYS

API_KEY = "YOUR_BYBIT_API_KEY"
API_SECRET = "YOUR_BYBIT_SECRET_KEY"
CRYPTOPANIC_TOKEN = "YOUR_CRYPTOPANIC_TOKEN"

# Settings
RISK_PER_TRADE = 5.0
MAX_POSITION_SIZE = 50.0
ATR_MULTIPLIER_SL = 2.0
ATR_MULTIPLIER_TP = 4.0
EOF
echo "✅ config_example.py created (Safe template)"

# 4. Create a README.md
cat <<EOF > README.md
# 🤖 Python Crypto Trading Bot (Expert + God Mode)

This is an algorithmic trading bot for Bybit that uses:
- **Expert Mode:** Technical Analysis (RSI, MACD, Volume, ATR).
- **God Mode:** News Sentiment Analysis (RSS Feeds) to detect crashes/wars.
- **Risk Management:** Dynamic position sizing and Trailing Stop Losses.

## Setup
1. Clone the repo.
2. Run \`pip install -r requirements.txt\`
3. Rename \`config_example.py\` to \`config.py\` and add your keys.
4. Run \`python3 master_bot.py\`
EOF
echo "✅ README.md created"

# 5. Initialize Git
if [ -d ".git" ]; then
    echo "ℹ️  Git already initialized."
else
    git init
    git branch -M main
    echo "✅ Git repository initialized"
fi

# 6. Add files (ignoring the secret ones automatically)
git add .
git commit -m "Initial export of Trading Bot"

echo ""
echo "🎉 SUCCESS! Your code is ready and safe."
echo "------------------------------------------------------"
echo "👇 FINAL STEP: PUSH TO GITHUB"
echo "1. Go to https://github.com/new and create an empty repository."
echo "2. Run these two commands to upload it:"
echo ""
echo "   git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git"
echo "   git push -u origin main"
echo "------------------------------------------------------"
