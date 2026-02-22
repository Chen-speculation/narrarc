#!/usr/bin/env python3
"""Generate 120+ message mock data for UI design, demonstrating relationship evolution."""

import json
from datetime import datetime, timedelta

# Phase 1: 热恋期 2023.03-2023.05 (~35 msgs) - 快速回复、宝贝、晚安
PHASE1_MSGS = [
    (True, "今天好累，被老板骂了一顿"),
    (False, "宝贝！怎么了，说来听听"),
    (True, "就说我报告数据不对，其实是他自己改了需求"),
    (False, "气死我了！你已经很厉害了，不用理他"),
    (False, "周末去吃你最喜欢的火锅？"),
    (True, "好呀好呀！爱你"),
    (False, "晚安宝贝❤"),
    (True, "晚安❤"),
    (True, "早上好呀"),
    (False, "早呀宝贝，睡得好吗"),
    (True, "梦到你了哈哈"),
    (False, "我也是！今天想我了吗"),
    (True, "想了呀，你忙不忙"),
    (False, "还好，等会开会，开完找你"),
    (True, "好哒，等你"),
    (False, "开完了！累死我了"),
    (True, "辛苦啦，晚上一起吃饭？"),
    (False, "好呀好呀，我去接你"),
    (True, "爱你"),
    (False, "我也爱你宝贝"),
    (True, "今天天气好好"),
    (False, "是呀，要不要出去走走"),
    (True, "好呀，去哪"),
    (False, "去你上次说的那个公园吧"),
    (True, "好！我马上出门"),
    (False, "不急，慢慢来，我等你"),
    (True, "到了到了"),
    (False, "看到你了！"),
    (True, "今天好开心"),
    (False, "我也是宝贝，下次再一起"),
    (True, "嗯嗯，晚安"),
    (False, "晚安，做个好梦"),
    (True, "你也是❤"),
    (False, "么么哒"),
    (True, "今天加班到好晚"),
]

# Phase 2: 第一道裂痕 2023.06-2023.08 (~35 msgs) - 回复变慢、哦、嗯
PHASE2_MSGS = [
    (True, "今天老板又骂我了，一整天都在加班"),
    (False, "哦"),  # 3小时后
    (True, "你昨晚睡了？"),
    (False, "嗯，困了"),
    (True, "你最近是不是很忙"),
    (False, "还行"),
    (True, "感觉你回我越来越慢了"),
    (False, "没有吧，可能最近事多"),
    (True, "好吧，那你注意休息"),
    (False, "嗯"),
    (True, "周末有空吗"),
    (False, "不确定，可能要加班"),
    (True, "好吧"),
    (False, "嗯"),
    (True, "你今天心情不好吗"),
    (False, "没有，就是累"),
    (True, "要不要聊聊"),
    (False, "改天吧，今天想静静"),
    (True, "好"),
    (False, "嗯"),
    (True, "我买了你爱吃的"),
    (False, "谢谢"),
    (True, "你以前都会说宝贝谢谢的"),
    (False, "……现在不是一样吗"),
    (True, "感觉不一样了"),
    (False, "你想多了"),
    (True, "希望是吧"),
    (False, "嗯"),
    (True, "晚安"),
    (False, "晚安"),
    (True, "你昨天没回我晚安"),
    (False, "睡了，没看到"),
    (True, "好吧"),
    (False, "嗯"),
    (True, "我们好久没一起吃饭了"),
]

# Phase 3: 冲突激化 2023.09-2023.11 (~35 msgs)
PHASE3_MSGS = [
    (True, "你最近是不是不想理我"),
    (False, "没有，就是最近压力大"),
    (True, "你压力大我理解，但你有没有想过我也需要你"),
    (False, "好了好了，我知道了"),
    (True, "你能不能好好说话"),
    (False, "我真的很累"),
    (True, "每次都是你累，那我呢"),
    (False, "你能不能别这样"),
    (True, "我怎样了？我只是想和你说话"),
    (False, "我现在不想说"),
    (True, "你变了"),
    (False, "随便你怎么想"),
    (True, "我们到底怎么了"),
    (False, "没什么，就是累了"),
    (True, "你是不是不爱我了"),
    (False, "……你能不能别问这种问题"),
    (True, "那我该问什么"),
    (False, "我不知道"),
    (True, "我们谈谈吧"),
    (False, "谈什么"),
    (True, "谈我们的关系"),
    (False, "没什么好谈的"),
    (True, "你什么意思"),
    (False, "字面意思"),
    (True, "你以前不是这样的"),
    (False, "人都会变的"),
    (True, "所以你是承认你变了"),
    (False, "随你怎么理解"),
    (True, "我真的很难过"),
    (False, "……"),
    (True, "你连安慰都不愿意了吗"),
    (False, "我不知道说什么"),
    (True, "好吧"),
    (False, "嗯"),
    (True, "我想我们需要冷静一下"),
]

# Phase 4: 仪式消失与终点 2023.12-2024.02 (~25 msgs)
PHASE4_MSGS = [
    (True, "晚安"),
    # TA 无回复
    (True, "在吗"),
    (False, "在"),
    (True, "昨天怎么没回"),
    (False, "睡了"),
    (True, "好吧"),
    (False, "嗯"),
    (True, "圣诞快乐"),
    (False, "嗯，你也是"),
    (True, "就这？"),
    (False, "不然呢"),
    (True, "我们真的回不去了吗"),
    (False, "……"),
    (True, "新年快乐"),
    (False, "新年快乐"),
    (True, "情人节了"),
    (False, "嗯"),
    (True, "我们谈谈吧"),
    (False, "谈什么"),
    (True, "谈我们还有没有可能"),
    (False, "我不知道"),
    (True, "那你想想吧"),
    (False, "好"),
    (True, "我等你"),
]


def ts(year: int, month: int, day: int, hour: int, minute: int) -> int:
    dt = datetime(year, month, day, hour, minute)
    return int(dt.timestamp() * 1000)


def generate_messages():
    """Generate 120+ messages with timestamps spread across relationship phases."""
    messages = []
    local_id = 1

    # Phase 1: 2023.03.10 - 2023.05.20, ~2 messages per day
    base = datetime(2023, 3, 10, 22, 10)
    for i, (is_send, content) in enumerate(PHASE1_MSGS):
        delta = timedelta(days=i // 2, hours=(i % 2) * 2, minutes=i * 3)
        t = base + delta
        messages.append({
            "local_id": local_id,
            "create_time": int(t.timestamp() * 1000),
            "is_send": is_send,
            "sender_display": "我" if is_send else "TA",
            "parsed_content": content,
        })
        local_id += 1

    # Phase 2: 2023.06.05 - 2023.08.25, longer gaps
    base = datetime(2023, 6, 5, 23, 41)
    for i, (is_send, content) in enumerate(PHASE2_MSGS):
        delta = timedelta(days=i * 2, hours=(i % 3) * 4, minutes=i * 5)
        t = base + delta
        messages.append({
            "local_id": local_id,
            "create_time": int(t.timestamp() * 1000),
            "is_send": is_send,
            "sender_display": "我" if is_send else "TA",
            "parsed_content": content,
        })
        local_id += 1

    # Phase 3: 2023.09.15 - 2023.11.20
    base = datetime(2023, 9, 15, 20, 0)
    for i, (is_send, content) in enumerate(PHASE3_MSGS):
        delta = timedelta(days=i * 2, hours=(i % 2) * 3, minutes=i * 7)
        t = base + delta
        messages.append({
            "local_id": local_id,
            "create_time": int(t.timestamp() * 1000),
            "is_send": is_send,
            "sender_display": "我" if is_send else "TA",
            "parsed_content": content,
        })
        local_id += 1

    # Phase 4: 2023.12.20 - 2024.02.14
    base = datetime(2023, 12, 20, 23, 55)
    for i, (is_send, content) in enumerate(PHASE4_MSGS):
        delta = timedelta(days=i * 5, hours=(i % 2) * 2, minutes=i)
        t = base + delta
        messages.append({
            "local_id": local_id,
            "create_time": int(t.timestamp() * 1000),
            "is_send": is_send,
            "sender_display": "我" if is_send else "TA",
            "parsed_content": content,
        })
        local_id += 1

    return messages


def build_evidence_from_messages(all_msgs, phase_evidence_ids):
    """Build evidence array from all_messages by local_id."""
    by_id = {m["local_id"]: m for m in all_msgs}
    return [
        {**by_id[lid], "phase_index": pi}
        for pi, ids in phase_evidence_ids.items()
        for lid in ids
        if lid in by_id
    ]


def main():
    all_messages = generate_messages()
    print(f"Generated {len(all_messages)} messages", flush=True)

    # Evidence: pick representative messages for each phase (local_id)
    # Phase 1: 1-35, 亲昵
    # Phase 2: 36-70, 哦、嗯
    # Phase 3: 71-105, 冲突
    # Phase 4: 106-130, 晚安无回复、谈谈
    phase_evidence = {
        1: [2, 5, 7, 10, 20],
        2: [36, 37, 39, 42, 50],
        3: [71, 73, 77, 85, 95],
        4: [106, 107, 115, 120, 130],
    }

    evidence_by_phase = {}
    for pi, ids in phase_evidence.items():
        evidence_by_phase[pi] = [
            {**m, "phase_index": pi}
            for m in all_messages
            if m["local_id"] in ids
        ]

    phases = [
        {
            "phase_index": 1,
            "phase_title": "热恋期",
            "time_range": "2023年3月 - 5月",
            "core_conclusion": "关系处于高能量状态。TA 反应迅速（回复延迟 < 1分钟），使用亲昵称呼（宝贝、么么哒），主动提供情感支持，每天维持晚安仪式，约会频繁。",
            "evidence": evidence_by_phase[1],
            "reasoning_chain": "回复延迟 < 1min + 亲昵称呼 + 主动安慰 + 约会提议 + 每日晚安 → 情感投入度高，亲密仪式稳定。",
            "uncertainty_note": "阶段内消息密度高，能较好反映互动模式。",
            "verified": True,
        },
        {
            "phase_index": 2,
            "phase_title": "第一道裂痕",
            "time_range": "2023年6月 - 8月",
            "core_conclusion": "同样是工作被批评，TA 回复延迟显著增加，称呼从「宝贝」消失，首次出现「哦」「嗯」等单字回避词，情感支持质量骤降，约会意愿下降。",
            "evidence": evidence_by_phase[2],
            "reasoning_chain": "回复延迟增加 + 首次回避词「哦」「嗯」+ 无情感内容 + 「改天吧」「想静静」→ 亲密互动模式首次发生结构性变化。",
            "uncertainty_note": "也可能 TA 工作压力确实增大，但回避式回应在情感表达上明显低于此前水平。",
            "verified": True,
        },
        {
            "phase_index": 3,
            "phase_title": "冲突激化",
            "time_range": "2023年9月 - 11月",
            "core_conclusion": "情感需求冲突显性化。你表达「我也需要你」「你变了」，TA 回应冷淡（「好了好了」「随便你怎么想」「随你怎么理解」），沟通模式断裂。",
            "evidence": evidence_by_phase[3],
            "reasoning_chain": "情感诉求 + 回避式/敷衍回应 + 「人都会变的」→ 冲突强度高，双方对关系的认知出现分歧。",
            "uncertainty_note": "冲突可能促进沟通，也可能加速疏远，需结合后续阶段判断。",
            "verified": True,
        },
        {
            "phase_index": 4,
            "phase_title": "仪式消失与终点",
            "time_range": "2023年12月 - 2024年2月",
            "core_conclusion": "晚安仪式消失（TA 无回复），节日祝福敷衍（「嗯，你也是」），你主动提出「我们谈谈吧」「还有没有可能」，TA 回应「我不知道」「好」。",
            "evidence": evidence_by_phase[4],
            "reasoning_chain": "对比阶段1的每日晚安，此处晚安无回复；节日互动质量骤降；「谈谈」暗示关系需要重新定义。",
            "uncertainty_note": "TA 未回复晚安可能有多种原因，但结合前期裂痕，仪式消失具有象征意义。",
            "verified": True,
        },
    ]

    output = {
        "conversation_id": "conv_mock_120",
        "question": "我们是怎么一步步分手的？",
        "phases": phases,
        "agent_trace": {
            "steps": [
                {
                    "node_name": "planner",
                    "node_name_display": "意图解析",
                    "input_summary": "用户问题：我们是怎么一步步分手的？",
                    "output_summary": "解析为 arc_narrative，关注维度：reply_delay, conflict_intensity, silence_event, term_shift",
                    "llm_calls": 1,
                    "timestamp_ms": 1707922810000,
                },
                {
                    "node_name": "retriever",
                    "node_name_display": "检索锚点与节点",
                    "input_summary": "按 focus_dimensions 查询异常锚点",
                    "output_summary": f"命中多个锚点，沿线程扩展得 20+ 候选节点，覆盖 {len(all_messages)} 条消息",
                    "llm_calls": 0,
                    "timestamp_ms": 1707922812000,
                },
                {
                    "node_name": "grader",
                    "node_name_display": "证据评估",
                    "input_summary": "已收集 20+ 个节点，覆盖 2023.03 - 2024.02",
                    "output_summary": "信息充足，可生成叙事",
                    "llm_calls": 1,
                    "timestamp_ms": 1707922815000,
                },
                {
                    "node_name": "generator",
                    "node_name_display": "叙事生成",
                    "input_summary": "20+ 个节点摘要 + 消息预览",
                    "output_summary": "生成 4 个叙事阶段，证据验证全部通过",
                    "llm_calls": 1,
                    "timestamp_ms": 1707922820000,
                },
            ],
            "total_llm_calls": 3,
            "total_duration_ms": 12000,
        },
        "all_messages": all_messages,
    }

    out_path = "docs/mock/query_response_120.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"Written to {out_path}")


if __name__ == "__main__":
    main()
