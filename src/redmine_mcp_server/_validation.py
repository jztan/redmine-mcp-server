"""Input validation helpers used across MCP tools."""

import math
import re
from datetime import date, datetime
from typing import Any, Optional

# Query parameters that replace, rather than add to, a Redmine query's
# filters. `fields` -- and its `f` alias -- is the list of fields a query
# filters on, and that branch empties the query's filters before rebuilding
# them from the request. `query_id` selects a saved query, which Redmine's
# `retrieve_query` prefers over anything built from the request. Forwarding any
# of them silently discards every other filter and answers HTTP 200 with the
# wrong set. This belongs to Redmine's query builder rather than to any one
# resource, so any tool forwarding a caller-supplied filter dict should reject
# them.
_RESERVED_QUERY_KEYS = frozenset({"fields", "f", "query_id"})


def _reject_reserved_query_keys(filters: Any) -> Optional[str]:
    """Return an error message if ``filters`` carries a reserved query key.

    Rack parses ``f[]`` into ``params[:f]`` and ``fields[]`` into
    ``params[:fields]``, so the bracketed spellings reach the same branch and
    are matched here too. Returns ``None`` when the dict is safe to forward.
    """
    if not isinstance(filters, dict):
        return None
    reserved = sorted(
        key
        for key in filters
        if isinstance(key, str)
        and (key[:-2] if key.endswith("[]") else key) in _RESERVED_QUERY_KEYS
    )
    if not reserved:
        return None
    return (
        f"filters may not contain {', '.join(reserved)}: Redmine reads it as "
        "the query's own filter definition and discards the filters built "
        "from the rest of the request, so every other filter would be lost."
    )


# Value types a Redmine query filter can carry. `Query#add_short_filter`
# (`app/models/query.rb:745-755` on 6.1) reads a filter value as one string --
# an optional operator prefix, then `|`-joined alternatives -- so a filter
# value is always a single scalar. `date` and `datetime` are here because
# python-redmine's `BaseResource.decode` formats them into Redmine's own date
# and datetime strings before the request goes out; `bool` is listed for
# intent, `is_public` being a yes/no filter, even though it is an `int`
# subclass already.
_FILTER_VALUE_TYPES = (str, int, float, date, datetime)

# A custom field filter, in every spelling Redmine registers.
# `Query#add_custom_field_filter` names it `cf_<id>`;
# `add_chained_custom_field_filters` (`app/models/query.rb:1552-1573` on 6.1)
# also registers `cf_<id>.cf_<chained id>` when the field's format has a
# target class, and `add_custom_fields_filters` (`:1577-1600`) adds
# `cf_<id>.due_date` and `cf_<id>.status` for a version-format field. Those
# formats are allowed on a project custom field as much as on an issue one --
# `RecordList.customized_class_names` includes `Project`
# (`lib/redmine/field_format.rb:766`) -- so the dotted spellings are reachable
# and refusing them would refuse a filter the server does register. The
# subfield is enumerated rather than left open, because those three are all
# `add_available_filter` is ever handed a dotted name for.
_CUSTOM_FIELD_FILTER_PATTERN = re.compile(r"^cf_\d+(?:\.(?:cf_\d+|due_date|status))?$")

# A query can also register a custom field filter on an *association*, under
# `<association>.cf_<id>`. `add_associations_custom_fields_filters`
# (`app/models/query.rb` on 6.1) is handed `:project, :author, :assigned_to,
# :fixed_version` by `IssueQuery` and `:author, :assigned_to` by the CRM
# plugin's `ContactQuery`, so which prefixes exist is a property of the
# resource and is passed in rather than assumed here. `ProjectQuery` makes no
# such call, which is why the default is empty and the project list's
# behaviour is unchanged.
_ASSOCIATION_CUSTOM_FIELD_PATTERN = re.compile(r"^cf_\d+$")


def _is_custom_field_filter(key: str, associations: "frozenset[str]") -> bool:
    """True when ``key`` is a custom field filter in a spelling Redmine registers."""
    if _CUSTOM_FIELD_FILTER_PATTERN.match(key):
        return True
    prefix, _, rest = key.partition(".")
    return bool(
        rest
        and prefix in associations
        and _ASSOCIATION_CUSTOM_FIELD_PATTERN.match(rest)
    )


def _association_clause(associations: "frozenset[str]") -> str:
    """The fragment naming the association custom field forms, or nothing."""
    if not associations:
        return ""
    names = ", ".join(f"{name}.cf_<id>" for name in sorted(associations))
    return f", and {names}"


def _reject_unregistered_filter_keys(
    filters: Any,
    registered: "frozenset[str]",
    associations: "frozenset[str]" = frozenset(),
) -> Optional[str]:
    """Return an error message if ``filters`` carries a non-filter key.

    ``registered`` is the resource's own set of filter names, as its ``Query``
    subclass hands them to ``add_available_filter``. ``cf_<id>`` and its
    chained spellings are accepted on top of that set, since those are
    registered per custom field and so cannot be enumerated from here, as is
    ``<association>.cf_<id>`` for each name in ``associations``. Refusing a
    spelling the resource does register would be worse than not checking at
    all, so a resource that registers association custom field filters must
    pass its association names.

    An allowlist rather than another denylist entry, because the two are not
    symmetric. Redmine builds its query from the filter parameters it
    registers and ignores every other one, so refusing an unregistered key
    costs a caller nothing it could have used. A key that is *not* a filter,
    on the other hand, can still mean something to another layer of the same
    request -- `key` is read as the request's API key ahead of the
    `X-Redmine-API-Key` header the client sets
    (`app/controllers/application_controller.rb:741-747` on 6.1), so it
    substitutes the identity the server was configured with -- and a denylist
    only ever names the vectors already found. Returns ``None`` when every key
    is a filter name.
    """
    if not isinstance(filters, dict):
        return None
    unknown = sorted(
        str(key)
        for key in filters
        if not (
            isinstance(key, str)
            and (key in registered or _is_custom_field_filter(key, associations))
        )
    )
    if not unknown:
        return None
    return (
        f"filters may not contain {', '.join(unknown)}: the accepted keys are "
        f"{', '.join(sorted(registered))}, plus cf_<id> for a custom field -- "
        "optionally chained as cf_<id>.cf_<id>, cf_<id>.due_date or "
        f"cf_<id>.status{_association_clause(associations)}. Redmine builds "
        "its query from the filter parameters "
        "it registers and ignores the rest, answering 200 with the unnarrowed "
        "collection, so a key it would not read as a filter is refused here "
        "rather than sent."
    )


def _reject_non_scalar_filter_values(filters: Any) -> Optional[str]:
    """Return an error message if a ``filters`` value is not a scalar.

    A Redmine filter value is one string: ``add_short_filter`` strips an
    operator prefix off it and splits the rest on ``|``, so nothing a filter
    needs is a list, a dict or ``None``. ``bool`` is refused too -- it
    urlencodes as ``True``, and a ``:list`` filter's values are ``"1"`` and
    ``"0"``, so it would pass a type check and then match nothing.

    Constraining the values also keeps a
    ``filters`` dict from reaching the parts of python-redmine's
    ``BaseResource.decode`` that treat a parameter as something other than a
    query parameter -- one branch walks a list of dicts and uploads each
    ``path`` it names before the request being asked for is issued -- since
    those branches need a container to act on. Returns ``None`` when every
    value is a scalar.
    """
    if not isinstance(filters, dict):
        return None
    bad = sorted(
        str(key)
        for key, value in filters.items()
        if isinstance(value, bool) or not isinstance(value, _FILTER_VALUE_TYPES)
    )
    if not bad:
        return None
    return (
        "filters values must each be a single scalar -- str, int, float, "
        f"date or datetime -- and {', '.join(bad)} is not. A filter's "
        "operator belongs inside the value, as a prefix Redmine strips off "
        '(">=2024-01-01", "~api"), and alternatives are joined with "|" '
        '("1|5"). Neither a list nor a dict reaches Redmine as a filter -- '
        "repeated query parameters keep only the last value -- and None is "
        "dropped from the query string before it is sent, either of which "
        "would leave the collection unnarrowed with a 200. A bool is refused "
        'for the same reason: it is sent as "True", which no Redmine filter '
        'value matches -- write a yes/no filter as "1" or "0".'
    )


def _is_positive_int(value: Any) -> bool:
    """Return True if ``value`` is a positive integer.

    Rejects booleans (``True`` is a subclass of ``int`` in Python, so a
    plain ``isinstance(x, int)`` would accept ``True`` as ``1`` — which
    lets an attacker silently pass role ID 1 or user ID 1). Rejects
    floats, strings, and non-positive integers.
    """
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


# Matches Redmine's project identifier rule: must start with a lowercase
# letter or digit, then lowercase letters / digits / hyphens / underscores,
# up to 100 chars total. Restricts the URL-path charset so callers cannot
# smuggle ``/``, ``?``, ``#``, ``..``, whitespace, or uppercase into paths.
_PROJECT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,99}$")


def _is_valid_project_id(value: Any) -> bool:
    """Return True if ``value`` is a usable Redmine project identifier.

    Accepts a positive integer (numeric ID) or a string matching Redmine's
    project-identifier rule (``^[a-z0-9][a-z0-9_-]{0,99}$``). Strings
    containing path-injecting characters (``/``, ``?``, ``#``, ``..``,
    whitespace) or uppercase letters are rejected. Used by tools that
    interpolate ``project_id`` directly into URL paths.
    """
    if _is_positive_int(value):
        return True
    if isinstance(value, str) and _PROJECT_ID_PATTERN.match(value):
        return True
    return False


def _validate_hours(value: Any) -> Optional[str]:
    """Validate a time-entry ``hours`` value.

    Returns None if the value is acceptable (a finite positive number),
    otherwise an error message suitable for returning to the caller.

    Rejects:
    - None, strings, and other non-numeric types
    - Booleans (True is a subclass of int and would otherwise pass)
    - NaN and +/-Infinity
    - Zero and negative values
    """
    # Booleans are instances of int in Python — reject explicitly.
    if isinstance(value, bool):
        return "Hours must be a positive, finite number (got boolean)."
    if not isinstance(value, (int, float)):
        return "Hours must be a positive, finite number."
    if math.isnan(value) or math.isinf(value):
        return "Hours must be a positive, finite number (got NaN or Infinity)."
    if value <= 0:
        return "Hours must be a positive number."
    return None
