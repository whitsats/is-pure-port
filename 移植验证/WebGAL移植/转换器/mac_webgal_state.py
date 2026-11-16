"""Generate WebGAL operations for explicitly tracked, non-aliasing MAC operands."""
from mac_state import CALC_STORE_IMMEDIATE, State, UnsupportedCommand, parse_reg_calc, to_s16


def variable(operand):
    return f'mac_{operand:04x}'


# 能用 setVar 表达式精确表达的运算。乘、除、余依赖 % 与向零截断，
# 已在引擎依赖 angular-expressions 上实测：(−7)%(2)=−1、((−7)−((−7)%(2)))/(2)=−3。
# 位运算 6/7 不被该表达式引擎支持（`&` 词法错误、`|` 语法错误），继续显式拒绝。
SUPPORTED_OPERATIONS = (1, 2, 3, 4, 5, 0x0F)


def emit_word_write(raw, tracked_words, label_suffix):
    operation, destination, source = parse_reg_calc(raw)
    layout = State()
    target = layout.describe(destination)
    for word in tracked_words:
        tracked = layout.describe(word)
        offset = tracked['offset']
        if target['kind'] == 'value' or destination == word:
            continue
        start = target['offset']
        end = start + (2 if target['kind'] == 'word' else 1)
        if start < offset + (2 if tracked['kind'] == 'word' else 1) and offset < end and (
            target['kind'] != 'bit' or tracked['kind'] != 'bit'
        ):
            raise UnsupportedCommand(f'运行时字与其他操作数共享地址: {destination:#06x}')
    if destination not in tracked_words:
        return []
    name = variable(destination)
    rhs = layout.describe(source)
    if target['kind'] == 'bit':
        if operation == CALC_STORE_IMMEDIATE:
            return [f'setVar:{name}={source & 1} -next;']
        if operation == 0 and rhs['kind'] == 'value':
            return [f'setVar:{name}={rhs["value"] & 1} -next;']
        raise UnsupportedCommand(f'尚未支持运行时位运算: {operation:#04x}')
    if operation == CALC_STORE_IMMEDIATE:
        return [f'setVar:{name}={to_s16(source)} -next;']
    if rhs['kind'] == 'value':
        value = rhs['value']
    elif source in tracked_words:
        value = variable(source)
    else:
        raise UnsupportedCommand(f'缺少运行时来源: {source:#06x}')
    if operation == 0:
        return [f'setVar:{name}={value} -next;']
    if operation in (6, 7):
        raise UnsupportedCommand(f'WebGAL 表达式不支持位运算: 运算 {operation:#04x}')
    if operation not in SUPPORTED_OPERATIONS:
        raise UnsupportedCommand(f'未支持的 WebGAL 运算: {operation:#04x}')
    # 乘/除/余先算成整数，再用 %65536 归一化，最后用 ±65536 回绕到有符号 16 位。
    # WebGAL 的 setVar 由 angular-expressions 求值，`%` 的行为与 R5900 一样向零截断，
    # 因此 div 可用 ((a)-((a)%(b)))/(b) 精确表达；`&`/`|` 不支持，见 SUPPORTED_OPERATIONS。
    if operation == 3:
        expression = f'(({name})*({value}))%(65536)'
    elif operation == 4:
        expression = f'(({name})-(({name})%({value})))/({value})'
    elif operation == 5:
        expression = f'({name})%({value})'
    else:
        expression = f'{name}{"-" if operation == 2 else "+"}({value})'
    label = f'wrap_{label_suffix}'
    return [
        f'setVar:{name}={expression} -next;',
        f'jumpLabel:{label}_underflow -when={name}<-32768;',
        f'jumpLabel:{label}_overflow -when={name}>32767;',
        f'jumpLabel:{label}_done;',
        f'label:{label}_underflow;',
        f'setVar:{name}={name}+65536 -next;',
        f'jumpLabel:{label}_done;',
        f'label:{label}_overflow;',
        f'setVar:{name}={name}-65536 -next;',
        f'label:{label}_done;',
    ]
