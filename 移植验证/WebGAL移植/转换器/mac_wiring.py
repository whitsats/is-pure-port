"""已接进可玩样片的阻塞点：选项表与跨剧本跳转。

`scan_blockers` 用这张表把「已接线」从阻塞里单列出来，报告的 `blocker_total`
因此就是真实剩余数，不需要人工从总数里扣减。

每条都必须对应到样片里的实际生成物（由对应的生成器脚本产出）：

- `MAC_003:0x5A44` 第五组选项 → `新游戏动态第五选项` 的 `mac003_fifth.txt` 里那条 `choose:`；
- `MAC_003:0x6790` `ext_goto` → `mac003_fifth_branches.txt` 段末的 `changeScene:`；
- `MAC_004:0xA38` 第一组选项 → `新游戏动态MAC004` 的 `mac_004_0x00000c.txt` 里那条 `choose:`。

登记只说明「这一处已经用已核实的方式接好」，不改变它原先的阻塞类别：报告里
同时保留 `category`，所以 `choice`/`cross_script` 的已接线条数仍然可查。
"""

WIRED = {
    ('MAC_003.bin', 0x5A44): {
        'kind': 'choice',
        'category': 'choice',
        'scene': '历史样片/新游戏动态第五选项/public/game/scene/mac003_fifth.txt',
        'detail': '第五组选项：choose + 三项分支（原序号写回 0x6007）',
    },
    ('MAC_003.bin', 0x6790): {
        'kind': 'ext_goto',
        'category': 'cross_script',
        'scene': '历史样片/新游戏动态第五选项/public/game/scene/mac003_fifth_branches.txt',
        'detail': 'ext_goto 组 0 索引 4 → changeScene:mac_004_0x00000c.txt',
    },
    ('MAC_004.bin', 0xA38): {
        'kind': 'choice',
        'category': 'choice',
        'scene': '历史样片/新游戏动态MAC004/public/game/scene/mac_004_0x00000c.txt',
        'detail': 'MAC_004 第一组选项：choose + 两项分支（原序号写回 0x6007）',
    },
}


def wired_for(script, offset):
    """返回该偏移的接线信息；未接线时返回 None。"""
    return WIRED.get((script, offset))
