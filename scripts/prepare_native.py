#!/usr/bin/env python3
"""Apply the checked MLX-Serve 26.9.6 text-engine bridge to an isolated source tree.

All replacements require their expected upstream anchors. Use a fresh 26.9.6
checkout, not a production installation. Native sources are Apache-2.0; keep
the upstream LICENSE/NOTICE when distributing the resulting binary.
"""
import argparse
import shutil
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('source', type=Path)
args = parser.parse_args()
root = args.source
native = Path(__file__).resolve().parents[1] / 'native'


def change(name, replacements):
    path = root / name
    data = path.read_text()
    for before, after in replacements:
        if before not in data:
            raise SystemExit(f'Unsupported upstream source or already patched: {name}')
        data = data.replace(before, after, 1)
    path.write_text(data)


change('src/generate.zig', [
    ('const token_mask = @import("token_mask.zig");', 'const token_mask = @import("token_mask.zig");\nconst strict_mask = @import("strict_mask.zig");'),
    ('pub const Constraint = struct {', 'pub const Constraint = struct {\n    strict: ?*strict_mask.Mask = null,'),
    ('pub const SchemaConstraint = struct {', 'pub const SchemaConstraint = struct {\n    strict: ?strict_mask.Mask = null,'),
    ('        self.allocator = allocator;\n        self.schema = try json_schema.parse', '        self.allocator = allocator;\n        self.strict = null;\n        self.schema = try json_schema.parse'),
    ('        self.constraint = .{\n            .grammar = &self.grammar,', '''        if (schema_value == .object) {
            if (schema_value.object.get("x-alp-ebnf")) |value| {
                if (value != .string) return error.InvalidStrictGrammar;
                self.strict = try strict_mask.Mask.init(allocator, value.string, token_bytes);
            }
        }
        self.constraint = .{
            .strict = if (self.strict) |*value| value else null,
            .grammar = &self.grammar,'''),
    ('    pub fn deinit(self: *SchemaConstraint) void {', '    pub fn deinit(self: *SchemaConstraint) void {\n        if (self.strict) |*value| value.deinit();'),
    ('        var allowed = (try token_mask.buildMask(constraint.grammar, constraint.token_bytes, constraint.mask_buf)).allowed;', '        var allowed = if (constraint.strict) |strict| try strict.fill(constraint.mask_buf) else (try token_mask.buildMask(constraint.grammar, constraint.token_bytes, constraint.mask_buf)).allowed;'),
    ('        if (constraint.grammar.isComplete()) {', '        if (if (constraint.strict) |strict| strict.complete else constraint.grammar.isComplete()) {'),
    ('        if (allowed == 0) {\n            log.warn("[grammar] no token', '        if (allowed == 0) {\n            if (constraint.strict != null) return error.StrictMaskEmpty;\n            log.warn("[grammar] no token'),
    ('        if (token < constraint.token_bytes.bytes.len) {\n            if (constraint.token_bytes.bytes[token]) |bytes| {', '        if (constraint.strict) |strict| {\n            try strict.accept(token);\n        } else if (token < constraint.token_bytes.bytes.len) {\n            if (constraint.token_bytes.bytes[token]) |bytes| {'),
])

change('src/server.zig', [
    ('                // Extract the schema JSON string from the raw body', '''                if (declared.?.object.get("x-alp-ebnf") != null) {
                    if (has_tools) {
                        try sendErrorResponse(allocator, stream, "400 Bad Request", "invalid_request_error", "ALP strict masks require tools disabled and thinking disabled", 400);
                        return;
                    }
                    grammar_schema_val = declared.?;
                } else {
                // Extract the schema JSON string from the raw body'''),
    ('            } else if (std.mem.eql(u8, rf_type, "json_object")) {', '                }\n            } else if (std.mem.eql(u8, rf_type, "json_object")) {'),
    ('                log.warn("[grammar] schema parse failed ({s}); falling back to prompt-only enforcement\\n", .{@errorName(err)});', '''                if (sv == .object and sv.object.get("x-alp-ebnf") != null) {
                    try sendErrorResponse(allocator, stream, "503 Service Unavailable", "strict_constraint_error", "ALP strict mask initialization failed", 503);
                    return;
                }
                log.warn("[grammar] schema parse failed ({s}); falling back to prompt-only enforcement\\n", .{@errorName(err)});'''),
    ('    if (grammar_schema_val) |sv| {\n        if (has_tools) {', '''    if (grammar_schema_val) |sv| {
        if (sv == .object and sv.object.get("x-alp-ebnf") != null and enable_thinking) {
            try sendErrorResponse(allocator, stream, "400 Bad Request", "invalid_request_error", "ALP strict masks require thinking disabled", 400);
            return;
        }
        if (has_tools) {'''),
    ('    if (c.has_chat) try append_cap(allocator, &caps, &n_caps, "json_schema");', '    if (c.has_chat) {\n        try append_cap(allocator, &caps, &n_caps, "json_schema");\n        try append_cap(allocator, &caps, &n_caps, "alp_strict_grammar_v1");\n    }'),
    ('            try add(allocator, &b, &n, "json_schema");', '            try add(allocator, &b, &n, "json_schema");\n            try add(allocator, &b, &n, "alp_strict_grammar_v1");'),
])

change('build.zig', [
    ('build_options.addOption(bool, "macos_engines", true);', 'build_options.addOption(bool, "macos_engines", false);'),
    ('    addDs4Sources(b, mod);', '    // Dedicated MLX text build; other native engines remain in the stock binary.\n    mod.addCSourceFile(.{ .file = b.path("lib/alp_mask_bridge.c"), .flags = &.{"-O2"} });'),
    ('    addLlamaLib(b, mod);', '    // No embedded GGUF backend in the dedicated ALP text binary.'),
])
shutil.copy2(native / 'strict_mask.zig', root / 'src/strict_mask.zig')
shutil.copy2(native / 'alp_mask_bridge.c', root / 'lib/alp_mask_bridge.c')
print('Prepared isolated MLX text engine with fail-closed ALP token masks.')
