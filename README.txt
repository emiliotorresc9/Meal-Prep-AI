# 🥗 MealPrepAI

**MealPrepAI** is an AI-powered meal planning assistant designed to help students and young independent adults eat healthier and save time.  
It automatically generates personalized meal ideas based on your available ingredients, dietary goals, allergies, and budget — and sends the complete recipe, nutritional information, and shopping list straight to your email.

DEMO VIDEO HERE --> https://youtu.be/9EKCIdOVaVo

## 🌟 Motivation

As a student living independently, I work in the mornings and study in the afternoons, which leaves little time for meal planning.  
I noticed I was eating fast food more often and needed a faster, healthier way to plan my meals.  
Instead of spending time scrolling through TikTok or YouTube and manually writing grocery lists, I decided to automate the process with AI.

MealPrepAI was built to make **healthy eating effortless** — turning a 30-minute task into a 5-second workflow.

---

## ⚙️ Features

- 🧠 **Natural Language Input** — Describe what you have or want (e.g. *“I have rice and tuna, high protein dinner under 500 calories”*).
- 🍳 **Smart Recipe Generation** — The AI suggests personalized meal ideas based on your preferences and restrictions.
- 📊 **Nutritional Breakdown** — Each recipe includes macros, portions, and calorie information.
- 💸 **Budget Awareness** — Considers low-cost and quick-prep options for students.
- 📩 **Email Automation** — Sends the full recipe and shopping list automatically to your inbox.
- 🧩 **Scalable Design** — Built with modular Flask routes for easy expansion (e.g., grocery API or Google Calendar integration).

---

## 🧰 Tech Stack

| Component | Description |
|------------|-------------|
| **Backend** | Flask (Python) |
| **AI Model** | OpenAI API (`gpt-4o-mini` or `gpt-4o`) |
| **Frontend** | HTML + TailwindCSS |
| **Automation** | Python email integration (MIMEText) |
| **Development Tools** | Cursor.ai, ChatGPT for ideation and code refactoring |

---

## 🚀 How It Works

1. The user inputs meal goals or ingredients in natural language.  
2. Flask sends this data to the OpenAI model.  
3. The model generates recipes, including:
   - Ingredients list  
   - Portions and macros  
   - Estimated cost and prep time  
4. Flask formats the output and emails it directly to the user.

```mermaid
flowchart LR
A[User Input] --> B[Flask Backend]
B --> C[OpenAI API]
C --> D[Recipe JSON + Macros]
D --> E[Email Formatter]
E --> F[User Inbox]
