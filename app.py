import os, json, itertools
from flask import Flask, render_template, request, jsonify
from email.mime.text import MIMEText  # only used if you later enable /email
from openai import OpenAI

# ---------- App & OpenAI ----------
app = Flask(__name__)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# In-memory cache of last suggestions so /recipe can return details without re-generating
SUGGEST_CACHE = {}  # id -> recipe dict
_id_counter = itertools.count(1001)  # simple id generator

# ---------- Pages ----------
@app.route("/")
def index():
    return render_template("index.html")

# ---------- Suggest via AI (no JSON file) ----------
@app.post("/suggest")
def suggest():
    data = request.get_json() or {}
    meal_type = (data.get("meal_type") or "").strip().lower()
    goals = [g.strip().lower() for g in (data.get("goals") or [])]
    comments = (data.get("comments") or "").strip()
    limit = max(3, min(int(data.get("limit") or 5), 8))

    goal_text = ", ".join(goals) if goals else "none"
    meal_text = meal_type or "any"

    # Prompt to return STRICT JSON
    sys = (
        "You are Emil-ia, a helpful meal planner AI. "
        "Respond ONLY with valid JSON. No code fencing, no commentary."
    )
    user = f"""
Generate {limit} recipe ideas tailored to the following:
- Meal type: {meal_text}
- Goals: {goal_text}
- Notes from user (allergies, pantry items, servings, preferences): {comments or "none"}

For each recipe, return an object with:
- id: null (will be filled by server)
- title: short dish name
- meal_type: "breakfast" | "lunch" | "dinner" (best fit)
- goal: array of relevant goal strings (e.g., ["low_budget","high_protein"])
- time_min: integer minutes to prepare/cook
- cost_usd: approximate total cost per serving as a float
- macros: object {{ kcal: int, protein_g: int, carbs_g: int, fat_g: int }}
- ingredients: array of objects {{ name, qty, unit }} (8–14 items, rough but useful)

Return STRICT JSON like:
{{
  "recipes":[
    {{
      "id": null,
      "title":"Example",
      "meal_type":"lunch",
      "goal":["low_budget"],
      "time_min":20,
      "cost_usd":3.2,
      "macros":{{"kcal":450,"protein_g":30,"carbs_g":45,"fat_g":15}},
      "ingredients":[{{"name":"Chicken breast","qty":200,"unit":"g"}}]
    }},
    ...
  ]
}}
"""

    try:
        resp = client.responses.create(
            model="gpt-4.1-mini",
            input=[{"role":"system","content":sys},{"role":"user","content":user}],
        )
        raw = resp.output_text
        payload = json.loads(raw)
        recipes = payload.get("recipes", [])
    except Exception as e:
        return jsonify({"recipes": [], "error": f"AI error: {e}"}), 500

    # assign server ids + cache
    out = []
    SUGGEST_CACHE.clear()
    for r in recipes[:limit]:
        rid = next(_id_counter)
        r["id"] = rid
        # Ensure required keys exist
        r.setdefault("goal", [])
        r.setdefault("macros", {})
        r.setdefault("ingredients", [])
        out.append({
            "id": rid,
            "title": r.get("title", "Recipe"),
            "meal_type": r.get("meal_type", meal_text),
            "goal": r.get("goal", []),
            "time_min": r.get("time_min"),
            "cost_usd": r.get("cost_usd"),
            "macros": r.get("macros", {}),
            # include ingredients so first message can show them if user clicks immediately
            "ingredients": r.get("ingredients", []),
        })
        SUGGEST_CACHE[rid] = r  # keep full object

    return jsonify({"recipes": out})

# ---------- Recipe details ----------
@app.post("/recipe")
def recipe():
    data = request.get_json() or {}
    rid = int(data.get("id", 0))
    r = SUGGEST_CACHE.get(rid)
    if not r:
        return jsonify({"error": "recipe not found"}), 404

    return jsonify({
        "title": r.get("title"),
        "ingredients": r.get("ingredients", []),
        "cost_usd": float(r.get("cost_usd") or 0.0),
        "macros": r.get("macros", {}),
        "time_min": r.get("time_min"),
        "meal_type": r.get("meal_type"),
        "goal": r.get("goal", [])
    })

# ---------- AI instructions ----------
@app.post("/ai/instructions")
def ai_instructions():
    data = request.get_json() or {}
    r = data.get("recipe") or {}

    title = r.get("title", "Recipe")
    meal_type = r.get("meal_type", "")
    ingredients = r.get("ingredients", [])
    macros = r.get("macros", {})
    time_min = r.get("time_min")

    prompt = f"""
You are Emil-ia, a friendly cooking assistant.

Greet once: "Hi, I'm Emil-ia! I'm here to guide you through preparing {title}."
Then provide 5–8 numbered steps, each on its own line with a blank line between steps.
End with: "If you have any questions, let me know!"

Use only ENGLISH. Be warm and practical (heat level, timing, texture cues).
Context:
- Meal type: {meal_type}
- Estimated time: {time_min} min
- Macros: {json.dumps(macros)}
- Ingredients: {json.dumps(ingredients, ensure_ascii=False)}
"""

    try:
        resp = client.responses.create(model="gpt-4.1-mini", input=prompt)
        message = (resp.output_text or "").strip()
        formatted = message.replace("  ", " ").strip()
        return jsonify({"message": formatted})
    except Exception as e:
        return jsonify({"message": "(AI error) I couldn’t load the instructions right now.", "error": str(e)}), 500

# ---------- AI chat ----------
@app.post("/ai/chat")
def ai_chat():
    data = request.get_json() or {}
    msg = (data.get("message") or "").strip()
    r = data.get("recipe") or {}
    title = r.get("title", "the recipe")
    ingredients = r.get("ingredients", [])

    coach = (
        "You are Emil-ia, a helpful cooking coach. "
        "Always reply in ENGLISH, concise, friendly, with practical substitutions when relevant.\n"
        f"Recipe: {title}\n"
        f"Ingredients: {json.dumps(ingredients, ensure_ascii=False)}\n"
        f"User: {msg}"
    )

    try:
        resp = client.responses.create(model="gpt-4.1-mini", input=coach)
        return jsonify({"reply": (resp.output_text or "").strip()})
    except Exception as e:
        return jsonify({"reply": f"(error) {e}"}), 500

# (Optional) email endpoint kept for future
@app.post("/email")
def email():
    return jsonify({"ok": False, "error": "email not configured in this demo"}), 501

if __name__ == "__main__":
    # For local dev
    app.run(debug=True)
