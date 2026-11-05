# lab

Iva, a lab supervisor, introduces herself as an AI, chats briefly with the participant, then guides them through a chemistry protocol the Unity client runs. Unity owns the game state and judges every action; the backend never checks game logic, it turns the game's snapshots into what Iva knows and says.

## The task

A protocol of several compounds, shown on a panel. For each, the panel shows the compound's name, two reagent codes and the flask to use.

1. Take the right empty flask from the shelf and place it on the plate on the table.
2. Ask Iva about each code. Iva names the reagent, by its color and symbol, only when asked. Fetch that bottle from the reagent shelf and pour it into the flask.
3. With both reagents in, put the flask on the finishing station Iva names. The panel does not show it.
4. Store the finished compound on the storage shelf.
5. The next compound appears.

## Persona and speech

- Warm, patient and encouraging, and enjoys helping the participant succeed. Introduced by the name Iva, as an AI.
- Short spoken sentences, one thing at a time. The first compound is explained step by step; later ones get only what is new: "For this one we need the round-bottom flask." After a mistake, a little more detail again.
- Speaks the session's language, addressing the participant informally in German. Reagents are named by their color and the symbol on their bottle, both in the session's language ("das rote Reagenz mit dem Flammensymbol"); a code as letter and number ("D 3").
- Flasks and stations by their spoken names: `prompt.py` holds them per language.

## Opening

A fixed greeting, spoken verbatim once the client is ready, so every participant hears the same disclosure:

- English: "Hi, great to have you here! I'm Iva, an AI agent, and what I hear, say and answer is handled by several models. I can make mistakes, so if something I say seems off, just ask again. I'll be supervising you in the lab today. What should I call you?"
- German: "Hallo, schön, dass du da bist! Ich bin Iva, eine KI-Agentin, und was ich höre, sage und antworte, übernehmen mehrere Modelle. Ich kann mich irren, also frag ruhig nach, wenn dir etwas komisch vorkommt. Ich betreue dich heute hier im Labor. Wie darf ich dich nennen?"

An intro follows, in Iva's own words over a few exchanges: she greets the participant by the name they give, asks one light question, and asks whether they are ready to start mixing. Once they are, she calls `start_task`, explains the task in two or three sentences, and gives the first step of the compound in progress. The explanation covers how many compounds there are, that each shows a flask and two codes on the panel, that the bottles do not reveal a code so the participant asks her, and that she names where the flask goes once both reagents are in. Asking about the task counts as ready.

During the intro the participant may already handle the equipment. Every snapshot still enters the context, but none is reacted to, and Iva gives no instructions. The name the participant gives appears in the transcripts of the study log.

## Game contract

- Unity sends a snapshot with `event: "state"` and `detail: null` once it has the agent's `session` message, and again after every reconnect. Events before that are dropped, not queued. An order with no recipes sends nothing, so Iva has no compound to start from when the task begins.
- Each event is a client-message `{"t": "game-event", "d": {...}}`, a full snapshot. `d` carries `event`, `detail`, `recipe` and `complete`.
  - `detail` is null when the event involves no flask or station; otherwise `flask` and `substance` are present only if a flask was involved, `station` only if a station was, and `substance` is null for an empty flask.
  - `recipe` carries `index` (from 0), `count`, `product`, `mixed`, `flask`, `station`, `ingredients` with `fetched` and `poured` each, `steps` (`flask_placed`, `combined`, `on_station`, `finished`) and `status` (`place_flask`, `awaiting_components`, `wrong_flask`, `wrong_mixture`, `place_on_station`, `wrong_station`, `store`, `complete`).
  - Flasks: `erlenmeyer`, `beaker`, `round_bottom`, and `reagent`, the small conical bottles on the endless-refill reagent shelf. Stations: `bunsen_burner` (heating), `magnetic_stirrer` (mixing), `ice_bath` (cooling).
  - A substance is `{name, code, color}` or null, with `color` as a name, in English in every session.
  - `recipe_loaded` is sent only for the first compound, before the agent connects, so it is dropped. `stored` carries the next compound in `recipe`.
  - The last compound ends with `game_complete` instead of `stored`; its snapshot still describes that compound, with `complete: true`.
- What Iva knows of an event expires: ten seconds after the newest snapshot, it stays in her context with `event` and `detail` set to null.

## Reactions

How each reaction behaves is in `ARCHITECTURE.md`. Until `start_task`, every event is `intro`; the table applies from then on.

| Event | Reaction |
|---|---|
| `state` | silent |
| `flask_placed`, `ingredient_fetched`, `ingredient_poured`, `combined`, `finished`, `stored`, `flask_emptied` | when idle |
| `wrong_flask`, `wrong_ingredient`, `wrong_mixture`, `wrong_station` | when idle |
| `recipe_loaded`, `placed_on_station` | silent |
| `game_complete` | interrupt |
| anything else | when idle, with a logged warning |
