"""Builds datasets/flask_seed.jsonl from a list of (question, target symbols).

The question wording and the choice of gold symbols are human judgment and live in QUESTIONS
below, where a reviewer can read them. The *line numbers* are resolved mechanically with the
stdlib ``ast`` module at the pinned commit, so nobody types a span by hand and the labels do
not depend on CodeAtlas's own Tree-sitter extractor.

Usage:
    python scripts/build_flask_seed.py <path-to-flask-clone>

Gold span rules:
    function/method -> first decorator line .. last line of the definition
    class ("header") -> the ``class`` line .. end of its docstring (or the class line alone)
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

REPO_URL = "https://github.com/pallets/flask"
COMMIT = "22d924701a6ae2e4cd01e9a15bbaf3946094af65"  # tag 3.1.3

# (id, category, question, [(file, dotted name inside file, ordinal among same-named defs, mode)])
Target = tuple[str, str, int, str]


def d(file: str, name: str, ordinal: int = 0) -> Target:
    return (file, name, ordinal, "def")


def h(file: str, name: str, ordinal: int = 0) -> Target:
    return (file, name, ordinal, "header")


APP = "src/flask/app.py"
CLI = "src/flask/cli.py"
HELPERS = "src/flask/helpers.py"
SESS = "src/flask/sessions.py"
CTX = "src/flask/ctx.py"
CONFIG = "src/flask/config.py"
SANSIO_APP = "src/flask/sansio/app.py"
SANSIO_BP = "src/flask/sansio/blueprints.py"
SCAFFOLD = "src/flask/sansio/scaffold.py"
PROVIDER = "src/flask/json/provider.py"
JSON_INIT = "src/flask/json/__init__.py"

QUESTIONS: list[tuple[str, str, str, list[Target]]] = [
    # --- symbol lookup: the query is (nearly) just an identifier
    ("q001", "symbol_lookup", "find_best_app", [d(CLI, "find_best_app")]),
    ("q002", "symbol_lookup", "stream_with_context", [d(HELPERS, "stream_with_context", 2)]),
    ("q003", "symbol_lookup", "get_debug_flag", [d(HELPERS, "get_debug_flag")]),
    (
        "q004",
        "symbol_lookup",
        "SecureCookieSessionInterface",
        [h(SESS, "SecureCookieSessionInterface")],
    ),
    ("q005", "symbol_lookup", "JSONProvider", [h(PROVIDER, "JSONProvider")]),
    (
        "q006",
        "symbol_lookup",
        "TaggedJSONSerializer",
        [h("src/flask/json/tag.py", "TaggedJSONSerializer")],
    ),
    ("q007", "symbol_lookup", "load_dotenv", [d(CLI, "load_dotenv")]),
    ("q008", "symbol_lookup", "AppContext", [h(CTX, "AppContext")]),
    # --- definition: "where is X defined / implemented"
    ("q009", "definition", "Where is the Flask class defined?", [h(APP, "Flask")]),
    (
        "q010",
        "definition",
        "Where is BlueprintSetupState defined?",
        [h(SANSIO_BP, "BlueprintSetupState")],
    ),
    ("q011", "definition", "Where is the routes command implemented?", [d(CLI, "routes_command")]),
    (
        "q012",
        "definition",
        "Where is send_from_directory defined?",
        [d(HELPERS, "send_from_directory")],
    ),
    (
        "q013",
        "definition",
        "Where is the signing serializer for the session cookie created?",
        [d(SESS, "SecureCookieSessionInterface.get_signing_serializer")],
    ),
    (
        "q014",
        "definition",
        "Where is session_transaction implemented for the test client?",
        [d("src/flask/testing.py", "FlaskClient.session_transaction")],
    ),
    # --- single hop: one place holds the answer, wording is conceptual
    (
        "q015",
        "single_hop",
        "How does Flask load configuration from an environment variable?",
        [d(CONFIG, "Config.from_envvar")],
    ),
    (
        "q016",
        "single_hop",
        "How can configuration values be loaded from a Python object or class?",
        [d(CONFIG, "Config.from_object")],
    ),
    (
        "q017",
        "single_hop",
        "How does a session backend decide whether to send a Set-Cookie header?",
        [d(SESS, "SessionInterface.should_set_cookie")],
    ),
    (
        "q018",
        "single_hop",
        "How are flashed messages stored for the next request?",
        [d(HELPERS, "flash")],
    ),
    (
        "q019",
        "single_hop",
        "How is a view function's return value turned into a response object?",
        [d(APP, "Flask.make_response")],
    ),
    (
        "q020",
        "single_hop",
        "How do I register a function to run when the application context is torn down?",
        [d(SANSIO_APP, "App.teardown_appcontext")],
    ),
    (
        "q021",
        "single_hop",
        "How does the interactive shell command build its context?",
        [d(CLI, "shell_command")],
    ),
    (
        "q022",
        "single_hop",
        "What happens when an unhandled exception occurs while handling a request?",
        [d(APP, "Flask.handle_exception")],
    ),
    (
        "q023",
        "single_hop",
        "How can code check whether a request context is currently active?",
        [d(CTX, "has_request_context")],
    ),
    (
        "q024",
        "single_hop",
        "How does the development server load environment variables from dotenv files?",
        [d(CLI, "load_dotenv")],
    ),
    # --- multi hop: the answer spans several definitions (verified by reading the call chain)
    (
        "q025",
        "multi_hop",
        "How does a request travel from the WSGI entry point "
        "through dispatching to the view function?",
        [
            d(APP, "Flask.wsgi_app"),
            d(APP, "Flask.full_dispatch_request"),
            d(APP, "Flask.dispatch_request"),
        ],
    ),
    (
        "q026",
        "multi_hop",
        "How does the route decorator end up registering a URL rule with the application?",
        [d(SCAFFOLD, "Scaffold.route"), d(SANSIO_APP, "App.add_url_rule")],
    ),
    (
        "q027",
        "multi_hop",
        "How does registering a blueprint add its URL rules to the application?",
        [
            d(SANSIO_BP, "Blueprint.register"),
            d(SANSIO_BP, "BlueprintSetupState.add_url_rule"),
            d(SANSIO_APP, "App.add_url_rule"),
        ],
    ),
    (
        "q028",
        "multi_hop",
        "How does jsonify build a JSON response using the application's JSON provider?",
        [d(JSON_INIT, "jsonify"), d(PROVIDER, "DefaultJSONProvider.response")],
    ),
    (
        "q029",
        "multi_hop",
        "How is the session loaded at the start of a request "
        "and saved when the response is produced?",
        [d(CTX, "RequestContext.push"), d(APP, "Flask.process_response")],
    ),
    (
        "q030",
        "multi_hop",
        "How does the flask command find and load the user's application?",
        [d(CLI, "ScriptInfo.load_app"), d(CLI, "locate_app", 2)],
    ),
    (
        "q031",
        "multi_hop",
        "How are exceptions raised in a view routed to a registered error handler?",
        [d(APP, "Flask.handle_user_exception"), d(APP, "Flask.handle_http_exception")],
    ),
]

UNANSWERABLE = [
    ("q032", "architecture", "How does Flask implement GraphQL schema stitching?"),
    ("q033", "architecture", "Which class implements the built-in database ORM layer?"),
]


def git_show(repo: Path, path: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), "show", f"{COMMIT}:{path}"], capture_output=True, check=True
    ).stdout
    return out.decode("utf-8").replace("\r\n", "\n")


def find_def(tree: ast.Module, dotted: str, ordinal: int) -> ast.stmt:
    """The ``ordinal``-th definition matching ``dotted`` (e.g. ``Flask.make_response``)."""
    parts = dotted.split(".")
    matches: list[ast.stmt] = []

    def walk(body: list[ast.stmt], prefix: list[str]) -> None:
        for node in body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                path = [*prefix, node.name]
                if path == parts:
                    matches.append(node)
                if isinstance(node, ast.ClassDef):
                    walk(node.body, path)

    walk(tree.body, [])
    if ordinal >= len(matches):
        raise LookupError(f"{dotted}#{ordinal}: only {len(matches)} matches")
    return matches[ordinal]


def span(node: ast.stmt, mode: str) -> tuple[int, int]:
    assert isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
    start = min([x.lineno for x in node.decorator_list] + [node.lineno])
    if mode == "header":
        first = node.body[0]
        is_doc = isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
        return start, (first.end_lineno or node.lineno) if is_doc else node.lineno
    assert node.end_lineno is not None
    return start, node.end_lineno


def main(repo: Path, out: Path) -> None:
    trees: dict[str, ast.Module] = {}
    records: list[dict[str, object]] = [{"_meta": {"repo": REPO_URL, "commit": COMMIT}}]
    for qid, category, question, targets in QUESTIONS:
        spans = []
        for file, dotted, ordinal, mode in targets:
            tree = trees.setdefault(file, ast.parse(git_show(repo, file)))
            start, end = span(find_def(tree, dotted, ordinal), mode)
            spans.append({"file_path": file, "start_line": start, "end_line": end})
        records.append({"id": qid, "question": question, "category": category, "gold_spans": spans})
    for qid, category, question in UNANSWERABLE:
        records.append(
            {
                "id": qid,
                "question": question,
                "category": category,
                "gold_spans": [],
                "answerable": False,
            }
        )
    out.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    print(f"wrote {len(records) - 1} questions to {out}")


if __name__ == "__main__":
    main(
        Path(sys.argv[1]), Path(__file__).resolve().parent.parent / "datasets" / "flask_seed.jsonl"
    )
