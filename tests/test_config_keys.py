"""A config key nobody reads is refused, not dropped.

Every parser in ``iaiops.core.runtime.config`` pulls its fields out with
``d.get(...)``, which means a key no parser names simply was not there. Writing
``rolle: good_count`` declared a production counter as far as the site was
concerned; ``readiness`` then reported the OEE mapping unmet — naming a gap the
operator had already filled, pointing nowhere near the typo. The config file
and the tool's idea of it had stopped being the same document, silently.

This is the repo's recurring shape rather than a one-off: the error flattered
us. A site that believes it declared its counters and is told it has not looks
like a site that needs more help.

The last class here is the one that keeps this honest. The accepted-key tables
live beside the parsers, not inside them, so they can drift — and a table that
has drifted refuses a key that works. ``TestTheTablesMatchTheParsers`` reads the
parsers' own source and fails when they do.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import pytest

from iaiops.core.runtime import config as config_mod
from iaiops.core.runtime.config import _parse_historian, _parse_target, load_config, parse_tags
from iaiops.core.runtime.config_keys import (
    ENDPOINT_KEYS,
    HISTORIAN_KEYS,
    RETENTION_KEYS,
    TAG_KEYS,
    BlockKeys,
    reject_unknown_keys,
)

pytestmark = pytest.mark.unit


def _endpoint(**extra) -> dict:
    return {"name": "e1", "protocol": "modbus", "host": "10.0.0.5", **extra}


def _write(tmp_path, text: str):
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


class TestTheReportedTypoIsRefused:
    """The reproducer from the report, whole."""

    def test_a_misspelled_role_no_longer_vanishes(self):
        with pytest.raises(ValueError) as excinfo:
            _parse_target(
                _endpoint(tags=[{"ref": "40001", "name": "GoodParts", "rolle": "good_count"}])
            )
        message = str(excinfo.value)
        assert "rolle" in message
        assert "role" in message

    def test_it_used_to_produce_a_tag_that_declared_nothing(self):
        """Guard on the OLD behaviour, so a revert cannot pass quietly: the tag
        was built, kept its ref, and lost both the label and the role."""
        with pytest.raises(ValueError):
            parse_tags([{"ref": "40001", "name": "GoodParts", "rolle": "good_count"}])


class TestTagKeys:
    def test_an_unknown_tag_key_is_refused(self):
        with pytest.raises(ValueError, match="warn_hihg"):
            parse_tags([{"ref": "1", "warn_hihg": 70}])

    def test_the_error_names_the_accepted_vocabulary(self):
        with pytest.raises(ValueError) as excinfo:
            parse_tags([{"ref": "1", "nonsense": 1}])
        message = str(excinfo.value)
        for key in TAG_KEYS.primary:
            assert key in message, f"the error does not name {key!r}"

    def test_the_error_locates_the_tag_and_the_endpoint(self):
        """A point list is long. "some tag is wrong" is not an answer."""
        with pytest.raises(ValueError) as excinfo:
            parse_tags([{"ref": "1"}, {"ref": "2"}, {"ref": "3", "junk": 1}], endpoint="line1")
        message = str(excinfo.value)
        assert "#3" in message
        assert "line1" in message

    def test_name_is_taught_as_label_though_it_is_no_misspelling(self):
        """``difflib`` cannot get from 'name' to 'label'; the rename table can."""
        with pytest.raises(ValueError) as excinfo:
            parse_tags([{"ref": "1", "name": "GoodParts"}])
        assert "label" in str(excinfo.value)

    def test_every_accepted_key_is_still_accepted(self):
        tags = parse_tags(
            [
                {
                    "ref": "1",
                    "label": "temp",
                    "warn_high": 70,
                    "alarm_high": 90,
                    "warn_low": 5,
                    "alarm_low": 1,
                    "role": "run_state",
                    "running_when": [2],
                }
            ]
        )
        assert tags[0].label == "temp"
        assert tags[0].role == "run_state"

    @pytest.mark.parametrize("alias", ["node_id", "address"])
    def test_the_documented_ref_aliases_survive(self, alias):
        """These are not in the headline vocabulary but they are real: refusing
        them would break every OPC-UA config written against the docs."""
        assert [t.ref for t in parse_tags([{alias: 7}])] == ["7"]

    def test_all_unknown_keys_are_reported_at_once(self):
        """One round trip should fix the whole entry, not the first key of it."""
        with pytest.raises(ValueError) as excinfo:
            parse_tags([{"ref": "1", "aaa": 1, "bbb": 2, "ccc": 3}])
        message = str(excinfo.value)
        assert "aaa" in message and "bbb" in message and "ccc" in message


class TestEndpointKeys:
    def test_an_unknown_endpoint_key_is_refused(self):
        with pytest.raises(ValueError, match="hsot"):
            _parse_target(_endpoint(hsot="10.0.0.6"))

    def test_the_error_names_the_endpoint(self):
        with pytest.raises(ValueError) as excinfo:
            _parse_target(_endpoint(junk=1))
        assert "e1" in str(excinfo.value)

    def test_a_near_miss_is_suggested(self):
        with pytest.raises(ValueError) as excinfo:
            _parse_target(_endpoint(hostname="10.0.0.6"))
        assert "host" in str(excinfo.value)

    def test_a_password_in_yaml_is_refused_with_where_it_belongs(self):
        """It was dropped before, so the operator saw an auth failure naming the
        endpoint and never the line they had typed the password on."""
        with pytest.raises(ValueError, match="(?i)secret set"):
            _parse_target(_endpoint(password="hunter2"))

    def test_a_tag_key_written_at_endpoint_level_says_where_it_goes(self):
        with pytest.raises(ValueError, match="(?i)tags"):
            _parse_target(_endpoint(role="run_state"))

    @pytest.mark.parametrize(
        "alias,field,expected",
        [
            ("broker", "host", "mq.lan"),
            ("com_port", "serial_port", "/dev/ttyS0"),
            ("interface", "nic", "eth1"),
            ("timeout", "timeout_s", 2.5),
        ],
    )
    def test_the_documented_endpoint_aliases_survive(self, alias, field, expected):
        entry = _endpoint(**{alias: expected})
        entry.pop(field, None)  # 'broker' only shows through when 'host' is absent
        target = _parse_target(entry)
        assert getattr(target, field) == expected


class TestHistorianKeys:
    def test_an_unknown_historian_key_is_refused(self):
        with pytest.raises(ValueError, match="databse"):
            _parse_historian({"reader": "sqlite", "databse": "iaiops"})

    def test_an_absent_block_is_still_no_historian(self):
        assert _parse_historian(None) is None
        assert _parse_historian({}) is None

    def test_a_block_with_settings_but_no_reader_is_refused(self):
        """It used to be discarded whole, so a site that had configured a
        historian was told, incident after incident, that it had none."""
        with pytest.raises(ValueError, match="(?i)reader"):
            _parse_historian({"host": "10.0.0.20", "database": "iaiops"})

    def test_a_scalar_block_is_refused(self):
        with pytest.raises(ValueError, match="(?i)mapping"):
            _parse_historian("sqlite")

    def test_a_password_in_yaml_is_refused_with_where_it_belongs(self):
        with pytest.raises(ValueError, match="(?i)secret set historian"):
            _parse_historian({"reader": "tdengine", "host": "h", "password": "x"})

    def test_every_accepted_key_is_still_accepted(self):
        historian = _parse_historian(
            {
                "reader": "tdengine",
                "host": "10.0.0.20",
                "port": 6041,
                "user": "root",
                "database": "iaiops",
                "db_path": "",
                "transport": "rest",
            }
        )
        assert historian is not None
        assert historian.reader == "tdengine"


class TestRetentionKeys:
    def test_an_unknown_retention_key_is_refused(self, tmp_path):
        path = _write(tmp_path, "retention:\n  days: 30\n")
        with pytest.raises(ValueError, match="raw_days"):
            load_config(path)

    def test_a_scalar_block_is_refused(self, tmp_path):
        path = _write(tmp_path, "retention: 30\n")
        with pytest.raises(ValueError, match="(?i)mapping"):
            load_config(path)

    def test_the_accepted_key_still_lands(self, tmp_path):
        path = _write(tmp_path, "retention:\n  raw_days: 30\n")
        assert load_config(path).retention_raw_days == 30

    def test_an_absent_block_leaves_the_decision_unmade(self, tmp_path):
        path = _write(tmp_path, "endpoints: []\n")
        assert load_config(path).retention_raw_days is None


class TestWholeFileLoad:
    """The parsers are reached through the file, not only when called directly."""

    def test_a_typo_deep_in_a_point_list_stops_the_load(self, tmp_path):
        path = _write(
            tmp_path,
            "endpoints:\n"
            "  - name: line1\n"
            "    protocol: modbus\n"
            "    host: 10.0.0.5\n"
            "    tags:\n"
            '      - {ref: "0", role: run_state, running_when: [2]}\n'
            '      - {ref: "10", rolle: total_count}\n',
        )
        with pytest.raises(ValueError, match="rolle"):
            load_config(path)

    def test_a_clean_file_still_loads(self, tmp_path):
        path = _write(
            tmp_path,
            "endpoints:\n"
            "  - name: line1\n"
            "    protocol: modbus\n"
            "    host: 10.0.0.5\n"
            "    ideal_cycle_time_s: 0.1\n"
            "    tags:\n"
            '      - {ref: "0", role: run_state, running_when: [2]}\n'
            '      - {ref: "10", role: total_count}\n'
            "historian:\n"
            "  reader: sqlite\n"
            "retention:\n"
            "  raw_days: 30\n",
        )
        config = load_config(path)
        assert config.targets[0].tags[1].role == "total_count"
        assert config.historian is not None
        assert config.retention_raw_days == 30


class TestSuggestionsAreHelpOrSilence:
    def test_a_key_resembling_nothing_gets_no_guess(self):
        """A wrong "did you mean" sends someone to the wrong line."""
        with pytest.raises(ValueError) as excinfo:
            parse_tags([{"ref": "1", "zzzzzzzz": 1}])
        assert "did you mean" not in str(excinfo.value).lower()

    def test_an_alias_suggestion_says_it_is_an_alias(self):
        spec = BlockKeys(what="Block", primary=("host",), aliases={"broker": "host"})
        with pytest.raises(ValueError, match="(?i)alias"):
            reject_unknown_keys(spec, {"brokr": "mq.lan"})

    def test_an_accepted_block_raises_nothing(self):
        reject_unknown_keys(TAG_KEYS, {"ref": "1", "role": "total_count"})


# --- the tables cannot drift away from the parsers -------------------------

#: (function, the parameter holding the raw block) → the table that must cover it.
_PARSERS = {
    ("_parse_target", "d"): ENDPOINT_KEYS,
    ("_modbus_transport", "d"): ENDPOINT_KEYS,
    ("_hart_transport", "d"): ENDPOINT_KEYS,
    ("_fins_transport", "d"): ENDPOINT_KEYS,
    ("_parse_timeout_s", "d"): ENDPOINT_KEYS,
    ("parse_tags", "t"): TAG_KEYS,
    ("_parse_historian", "block"): HISTORIAN_KEYS,
}


def _keys_read_from(func_name: str, var: str) -> set[str]:
    """String keys the function pulls out of ``var`` — ``var["x"]``/``var.get("x")``."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(getattr(config_mod, func_name))))
    found: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == var
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        ):
            found.add(node.slice.value)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == var
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            found.add(node.args[0].value)
    return found


class TestTheTablesMatchTheParsers:
    """A table that has fallen behind its parser refuses a key that works.

    That is the failure mode this split introduces, and it is worse than the bug
    being fixed — the config is right and the tool says it is wrong. So the
    tables are checked against the parsers' own source rather than against a
    second hand-written list.
    """

    @pytest.mark.parametrize(("func", "var", "spec"), [(f, v, s) for (f, v), s in _PARSERS.items()])
    def test_every_key_a_parser_reads_is_accepted(self, func, var, spec):
        read = _keys_read_from(func, var)
        assert read, f"read no keys out of {var!r} in {func} — the scan is broken, not the table"
        missing = read - spec.accepted
        assert not missing, (
            f"{func} reads {sorted(missing)} out of {var!r} but {spec.what} would refuse them"
        )

    def test_the_ref_aliases_are_accepted(self):
        """``_tag_ref`` reads its keys through a loop, so the scan cannot see them."""
        assert set(config_mod._REF_KEYS) <= TAG_KEYS.accepted

    def test_retention_reads_only_what_the_table_lists(self):
        assert _keys_read_from("load_config", "retention") <= RETENTION_KEYS.accepted

    def test_the_scan_would_notice_a_missing_key(self):
        """The check above is only worth its green if it can go red."""
        read = _keys_read_from("_parse_target", "d")
        assert "plctype" in read
        assert read - (ENDPOINT_KEYS.accepted - {"plctype"})


class TestABlockThatIsNotAMapping:
    """``tags: ["40001"]`` is a natural thing to write. It used to arrive as a
    TypeError about string indices, which names Python rather than the file."""

    def test_a_scalar_tag_entry_is_refused(self):
        with pytest.raises(ValueError, match="(?i)mapping"):
            parse_tags(["40001"])

    def test_a_scalar_endpoint_entry_is_refused(self, tmp_path):
        path = _write(tmp_path, "endpoints:\n  - line1\n")
        with pytest.raises(ValueError, match="(?i)mapping"):
            load_config(path)

    def test_the_refusal_still_names_the_vocabulary(self):
        with pytest.raises(ValueError) as excinfo:
            parse_tags(["40001"])
        assert "ref" in str(excinfo.value)


class TestEveryProblemAtOnce:
    """A file typed by hand has typos in the plural.

    Stopping at the first one makes a 50-endpoint config take as many round
    trips as it has mistakes, and each round trip is a walk back to whoever
    knows what that point actually is.
    """

    MESSY = (
        "endpoints:\n"
        "  - name: line1\n"
        "    protocol: modbus\n"
        "    hsot: 10.0.0.5\n"
        "  - name: line2\n"
        "    protocol: modbus\n"
        "    host: 10.0.0.6\n"
        "    tags:\n"
        '      - {ref: "10", rolle: total_count}\n'
        "historian:\n"
        "  host: 10.0.0.20\n"
        "retention:\n"
        "  days: 30\n"
    )

    def test_all_four_blocks_are_reported_together(self, tmp_path):
        with pytest.raises(ValueError) as excinfo:
            load_config(_write(tmp_path, self.MESSY))
        message = str(excinfo.value)
        for fragment in ("hsot", "rolle", "reader", "days"):
            assert fragment in message, f"{fragment!r} was not reported"
        assert "4 problems" in message

    def test_the_file_is_named(self, tmp_path):
        path = _write(tmp_path, self.MESSY)
        with pytest.raises(ValueError, match=r"config\.yaml"):
            load_config(path)

    def test_a_vocabulary_is_stated_once_however_many_entries_use_it(self, tmp_path):
        """Four endpoints wrong the same way must not print the 33-key endpoint
        vocabulary four times — that buries the four lines that differ."""
        many = "endpoints:\n" + "".join(
            f"  - name: line{n}\n    protocol: modbus\n    host: 10.0.0.{n}\n    junk{n}: 1\n"
            for n in range(1, 5)
        )
        with pytest.raises(ValueError) as excinfo:
            load_config(_write(tmp_path, many))
        message = str(excinfo.value)
        assert message.count("ideal_cycle_time_s") == 1, "the endpoint vocabulary repeats"
        for n in range(1, 5):
            assert f"junk{n}" in message

    def test_one_problem_stays_one_sentence(self, tmp_path):
        """The common case must not be dressed up as a report."""
        one = "endpoints:\n  - name: line1\n    protocol: modbus\n    host: 10.0.0.5\n    junk: 1\n"
        with pytest.raises(ValueError) as excinfo:
            load_config(_write(tmp_path, one))
        message = str(excinfo.value)
        assert "problems" not in message
        assert message.startswith("Endpoint 'line1'")

    def test_a_good_endpoint_beside_a_bad_one_does_not_rescue_the_file(self, tmp_path):
        """Half a config is not a config: loading the endpoints that parsed
        would hand back a fleet quietly missing the ones that did not."""
        with pytest.raises(ValueError):
            load_config(_write(tmp_path, self.MESSY))


class TestASuggestionIsNeverAGuess:
    def test_a_tie_is_reported_as_a_tie(self):
        """'hsot' scores 0.75 against both 'host' and 'slot'.
        ``difflib.get_close_matches`` breaks that by string order and returned
        'slot' — a confident pointer at a line that was already correct."""
        with pytest.raises(ValueError) as excinfo:
            _parse_target(_endpoint(hsot="10.0.0.6"))
        message = str(excinfo.value)
        assert "'host'" in message and "'slot'" in message

    def test_an_unambiguous_near_miss_is_still_a_single_answer(self):
        with pytest.raises(ValueError) as excinfo:
            _parse_target(_endpoint(hostt="10.0.0.6"))
        message = str(excinfo.value)
        assert "Did you mean 'host'?" in message
        assert "slot" not in message.split("Accepted")[0]


class TestTheRefusalSaysWhichVersionRefused:
    """ "I do not recognise this key" has two causes in the field: it is
    misspelled, or THIS box is older than the docs it was written against. An
    edge fleet is never on one version, and without this only the first cause
    occurs to anybody."""

    def test_the_running_version_is_named(self):
        from iaiops import __version__

        with pytest.raises(ValueError) as excinfo:
            parse_tags([{"ref": "1", "junk": 1}])
        assert f"iaiops {__version__}" in str(excinfo.value)

    def test_it_is_named_in_the_grouped_report_too(self, tmp_path):
        from iaiops import __version__

        with pytest.raises(ValueError) as excinfo:
            load_config(_write(tmp_path, TestEveryProblemAtOnce.MESSY))
        assert f"iaiops {__version__}" in str(excinfo.value)
