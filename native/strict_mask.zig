const std = @import("std");
const token_mask = @import("token_mask.zig");

extern "c" fn alp_mask_open(grammar: [*]const u8, len: usize, tokens: [*]const ?[*]const u8, lengths: [*]const usize, size: usize, eos: u32) ?*anyopaque;
extern "c" fn alp_mask_fill(handle: *anyopaque, mask: [*]u8, size: usize, complete: *c_int) c_int;
extern "c" fn alp_mask_accept(handle: *anyopaque, token: u32) c_int;
extern "c" fn alp_mask_close(handle: *anyopaque) void;

pub const Mask = struct {
    handle: *anyopaque,
    complete: bool = false,

    pub fn init(allocator: std.mem.Allocator, grammar: []const u8, tb: *const token_mask.TokenBytes) !Mask {
        const pointers = try allocator.alloc(?[*]const u8, tb.bytes.len);
        defer allocator.free(pointers);
        const lengths = try allocator.alloc(usize, tb.bytes.len);
        defer allocator.free(lengths);
        for (tb.bytes, 0..) |token, i| {
            pointers[i] = if (token) |s| s.ptr else null;
            lengths[i] = if (token) |s| s.len else 0;
        }
        const handle = alp_mask_open(grammar.ptr, grammar.len, pointers.ptr, lengths.ptr, tb.bytes.len, tb.eos_id orelse return error.StrictMaskMissingEOS) orelse return error.StrictMaskUnavailable;
        return .{ .handle = handle };
    }

    pub fn fill(self: *Mask, mask: []bool) !usize {
        var complete: c_int = 0;
        const count = alp_mask_fill(self.handle, @ptrCast(mask.ptr), mask.len, &complete);
        if (count < 0) return error.StrictMaskUnavailable;
        self.complete = complete == 1;
        return @intCast(count);
    }

    pub fn accept(self: *Mask, token: u32) !void {
        if (alp_mask_accept(self.handle, token) != 1) return error.StrictMaskRejectedToken;
    }

    pub fn deinit(self: *Mask) void { alp_mask_close(self.handle); }
};
