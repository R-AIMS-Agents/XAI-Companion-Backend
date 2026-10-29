# lab

Iva, a lab supervisor, guides the participant through a chemistry protocol the Unity client runs. Unity owns the game state and judges every action; the backend never checks game logic, it turns the game's snapshots into what Iva knows and says.

## The task

A protocol of several compounds, shown on a panel. For each, the panel shows the compound's name, two reagent codes and the flask to use.

1. Take the right empty flask from the shelf and place it on the plate on the table.
2. Ask Iva about each code. Iva names the reagent, by name and color, only when asked. Fetch that bottle from the reagent shelf and pour it into the flask.
3. With both reagents in, put the flask on the finishing station Iva names. The panel does not show it.
4. Store the finished compound on the storage shelf.
5. The next compound appears.

## Persona and speech

- Warm, patient and encouraging, and enjoys helping the participant succeed. Introduced by the name Iva.
- Short spoken sentences, one thing at a time. The first compound is explained step by step; later ones get only what is new: "For this one we need the round-bottom flask." After a mistake, a little more detail again.
- Speaks the session's language, addressing the participant informally in German. Reagent names and codes are said exactly as printed in English on the bottles, a code as letter and number ("D 3"); colors in the session's language.
- Flasks and stations by their spoken names: `prompt.py` holds them per language.

## Opening

No fixed greeting. The session's first snapshot runs the LLM, so Iva opens knowing the first compound: a welcome, the name Iva, and the first step.

## Game contract

- Unity sends a snapshot with `event: "state"` and `detail: null` once it has the agent's `session` message, and again after every reconnect. Events before that are dropped, not queued. An order with no recipes sends nothing, so Iva never opens and the participant stays muted.
- Each event is a client-message `{"t": "game-event", "d": {...}}`, a full snapshot. `d` carries `event`, `detail`, `recipe` and `complete`.
  - `detail` is null when the event involves no flask or station; otherwise `flask` and `substance` are present only if a flask was involved, `station` only if a station was, and `substance` is null for an empty flask.
  - `recipe` carries `index` (from 0), `count`, `product`, `mixed`, `flask`, `station`, `ingredients` with `fetched` and `poured` each, `steps` (`flask_placed`, `combined`, `on_station`, `finished`) and `status` (`place_flask`, `awaiting_components`, `wrong_flask`, `wrong_mixture`, `place_on_station`, `wrong_station`, `store`, `complete`).
  - Flasks: `erlenmeyer`, `beaker`, `round_bottom`, and `reagent`, the small conical bottles on the endless-refill reagent shelf. Stations: `bunsen_burner` (heating), `magnetic_stirrer` (mixing), `ice_bath` (cooling).
  - A substance is `{name, code, color}` or null, with `color` as a name, in English in every session.
  - The last compound ends with `game_complete` instead of `stored`; its snapshot still describes that compound, with `complete: true`.

## Reactions

How each reaction behaves is in `ARCHITECTURE.md`. The session's first snapshot is the opening, whatever its event.

| Event | Reaction |
|---|---|
| `state` after the first | silent |
| `recipe_loaded` | when idle; silent for index 0, which the opening covers |
| `flask_placed`, `ingredient_fetched`, `ingredient_poured`, `combined`, `finished`, `flask_emptied` | when idle |
| `wrong_flask`, `wrong_ingredient`, `wrong_mixture`, `wrong_station` | when idle |
| `placed_on_station`, `stored` | silent |
| `game_complete` | interrupt |
| anything else | when idle, with a logged warning |
