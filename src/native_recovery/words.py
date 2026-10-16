"""Exact word values at the CLI, JSON and browser boundaries."""

import re

_INTEGER = re.compile(r"-?(?:0x[0-9a-fA-F]+|[0-9]+)\Z")


def word_bits(value=32):
    if type(value) is not int or value not in (32, 64):
        raise ValueError("Word size must be 32 or 64 bits.")
    return value


def integer(value, bits=32, *, wire=False):
    word_bits(bits)
    if wire and bits == 64 and not isinstance(value, str):
        raise ValueError(
            "64-bit JSON values must be decimal or hexadecimal strings, never JSON numbers."
        )
    if type(value) is int:
        return value
    if isinstance(value, str) and len(value) <= 80 and _INTEGER.fullmatch(value):
        negative = value.startswith("-")
        text = value[1:] if negative else value
        result = int(text, 16 if text.startswith("0x") else 10)
        return -result if negative else result
    raise ValueError(
        "An exact integer is required; booleans and floating-point numbers are rejected."
    )


def pattern(value, bits=32, *, wire=False, signed=False):
    value = integer(value, bits, wire=wire)
    lower = -(1 << (bits - 1)) if signed else 0
    if not lower <= value < (1 << bits):
        raise ValueError(f"Value is outside the {bits}-bit range.")
    return value & ((1 << bits) - 1)


def normalize_request(request, *, wire=False):
    result = dict(request)
    bits = word_bits(request.get("word_bits", 32))
    result["word_bits"] = bits
    # Pointer declarations change the logical input count, never word precision.
    from .transitions import input_count
    count = input_count(request.get("arity"), request.get("memory"), bits)
    if "target" in request:
        result["target"] = pattern(request["target"], bits, wire=wire)
    if "inputs" in request:
        values = request["inputs"]
        if not isinstance(values, list):
            raise ValueError("Inputs must be a list of exact word values.")
        result["inputs"] = [pattern(v, bits, wire=wire) for v in values]
    domain = request.get("domain")
    if domain is not None:
        if not isinstance(domain, list) or len(domain) != count:
            raise ValueError("Domain must have one entry per logical input.")
        converted = []
        for item in domain:
            if item is None:
                converted.append(None)
                continue
            if (
                not isinstance(item, dict)
                or set(item) != {"min", "max", "signed"}
                or type(item["signed"]) is not bool
            ):
                raise ValueError(
                    "Domain entries require min/max and a boolean signed field."
                )
            lo = integer(item["min"], bits, wire=wire)
            hi = integer(item["max"], bits, wire=wire)
            lower, upper = (
                (-(1 << (bits - 1)), (1 << (bits - 1)) - 1)
                if item["signed"]
                else (0, (1 << bits) - 1)
            )
            if not lower <= lo <= hi <= upper:
                raise ValueError(
                    "Domain bounds must be ordered integers in the selected word range."
                )
            converted.append({"min": lo, "max": hi, "signed": item["signed"]})
        result["domain"] = converted
    return result


def encode_exact(value):
    if isinstance(value, dict):
        return {
            k: hex(v) if k in {"address","next_address","target_address"} and type(v) is int else encode_exact(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [encode_exact(v) for v in value]
    if type(value) is int and abs(value) > (1 << 53) - 1:
        return hex(value)
    return value
