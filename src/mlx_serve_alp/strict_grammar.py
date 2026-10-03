"""Exact finite-set arrays and escaped, bounded JSON strings for XGrammar.

The schema compiler in XGrammar 0.2.8 ignores uniqueItems and its bounded
string implementation excludes escapes. Replace those nodes with private
terminals, then substitute explicit EBNF productions before compiling.
"""
from __future__ import annotations

import hashlib
import json
import re

from .catalog import schema_children, stable_json
from .errors import ALPError
from .schema_tools import compact_schema


def literal(value):
    return json.dumps(value, ensure_ascii=False)


def strict_json_grammar(schema):
    import xgrammar as xgr

    source = compact_schema(schema, annotations=False)
    replacements = {}
    rules = []
    # A Unicode escape is one decoded character; a surrogate pair is one,
    # too. Excluding lone surrogates avoids emitting invalid Unicode values.
    rules.extend([
        r'alp_ws ::= [ \n\r\t]{0,16}',
        r'alp_hex ::= [0-9a-fA-F]',
        r'alp_char ::= [^"\\\x00-\x1f\uD800-\uDFFF] | "\\" ["\\/bfnrt] | "\\u" ([0-9a-cA-Ce-fE-F] alp_hex alp_hex alp_hex | [dD] [0-7] alp_hex alp_hex) | "\\u" [dD] [89aAbB] alp_hex alp_hex "\\u" [dD] [c-fC-F] alp_hex alp_hex',
    ])

    counts, exacts = set(), set()

    def exact(count):
        name = f'alp_exact_{count}'
        if count not in exacts:
            exacts.add(count)
            rhs = '""' if count == 0 else 'alp_char' if count == 1 else exact(count // 2) + ' ' + exact(count - count // 2)
            rules.append(name + ' ::= ' + rhs)
        return name

    def upto(count):
        # A bounded repeat of a multi-byte/escaped character rule causes
        # growing Earley states in XGrammar 0.2.8. Disjoint count ranges keep
        # the same accepted strings with bounded parsing work.
        name = f'alp_upto_{count}'
        if count not in counts:
            counts.add(count)
            if count == 0:
                rhs = '""'
            elif count <= 256:
                rhs = '"" | alp_char ' + upto(count - 1)
            else:
                half = (count + 1) // 2
                rhs = upto(half - 1) + ' | ' + exact(half) + ' ' + upto(count - half)
            rules.append(name + ' ::= ' + rhs)
        return name

    def replace(node, rhs):
        marker = '__alp_constraint_' + hashlib.sha256(
            (str(len(replacements)) + stable_json(node)).encode()
        ).hexdigest() + '__'
        rule = 'alp_special_' + str(len(replacements))
        replacements[literal(literal(marker))] = rule
        rules.append(rule + ' ::= ' + rhs)
        node.clear()
        node['const'] = marker

    def finite_array(node):
        items = node.get('items', {})
        values = items.get('enum') if isinstance(items, dict) else None
        if values is None:
            return False
        # Bound compilation cost explicitly instead of silently weakening it.
        if len(values) > 12 and node.get('x-alp-prefix-unique'):
            node.pop('uniqueItems', None)
            return False
        if len(values) > 12:
            raise ALPError('UNSUPPORTED_SCHEMA', 'Strict unique arrays support at most 12 candidate values.', 422)
        if not values:
            return False
        prefix = 'alp_set_' + str(len(replacements))
        n = len(values)
        minimum = node.get('minItems', 0)
        maximum = min(node.get('maxItems', n), n)
        index = {stable_json(value): i for i, value in enumerate(values)}
        required = sum(1 << index[stable_json(v)] for v in node.get('x-alp-required-items', []))
        any_required = sum(1 << index[stable_json(v)] for v in node.get('x-alp-any-items', []))
        groups = [sum(1 << index[stable_json(v)] for v in group)
                  for group in node.get('x-alp-together', []) if all(stable_json(v) in index for v in group)]
        for used in range(1 << n):
            count = used.bit_count()
            if count > maximum:
                continue
            choices = []
            if count >= minimum and used & required == required and (not any_required or used & any_required) and all(not used & g or used & g == g for g in groups):
                choices.append(literal(']'))
            if count < maximum:
                for i, value in enumerate(values):
                    if not used & (1 << i):
                        sep = '' if count == 0 else literal(',') + ' alp_ws '
                        choices.append(sep + literal(stable_json(value)) + ' alp_ws ' + prefix + '_' + str(used | (1 << i)))
            # States with an impossible cardinality are excluded by callers;
            # retain a syntactically valid, unreachable production otherwise.
            rules.append(prefix + '_' + str(used) + ' ::= ' + (' | '.join(choices) if choices else '[^\\u0000-\\U0010FFFF]'))
        replace(node, literal('[') + ' alp_ws ' + prefix + '_0')
        return True

    def walk(node):
        if not isinstance(node, dict):
            return
        if node.get('type') == 'array' and node.get('uniqueItems') and finite_array(node):
            return
        if node.get('type') == 'string' and not any(k in node for k in ('enum', 'const', 'pattern')) and any(k in node for k in ('minLength', 'maxLength')):
            low, high = node.get('minLength', 0), node.get('maxLength')
            if high is not None and low > high:
                raise ALPError('UNSUPPORTED_SCHEMA', 'String length constraints have an empty domain.', 422)
            count = exact(low) + ' ' + (upto(high - low) if high is not None else 'alp_char*')
            replace(node, literal('"') + ' ' + count + ' ' + literal('"'))
            return
        for child in list(schema_children(node)):
            walk(child)
        for key in ('x-alp-together', 'x-alp-required-items', 'x-alp-any-items', 'x-alp-prefix-unique'):
            node.pop(key, None)

    walk(source)
    grammar = str(xgr.Grammar.from_json_schema(source, any_order=False))
    # Whitespace is a formatting choice, not task content. An unbounded loop
    # lets a model consume its budget before closing the final object. Keep a
    # finite allowance at each JSON boundary; escaped string data is untouched.
    grammar = grammar.replace(r'[ \n\r\t]*', r'[ \n\r\t]{0,16}')
    for terminal, rule in replacements.items():
        if terminal not in grammar:
            # Unreachable $defs may legitimately disappear from the grammar.
            continue
        grammar = grammar.replace(terminal, rule)
    # Only use private rule names; an upstream naming collision is a hard error.
    if re.search(r'^alp_(?:ws|hex|char|special_|set_)', grammar, re.M):
        raise ALPError('GRAMMAR_COMPILE_FAILED', 'An upstream grammar rule conflicts with an ALP rule.', 422)
    return str(xgr.Grammar.from_ebnf(grammar + '\n' + '\n'.join(rules)))
