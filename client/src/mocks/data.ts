import { Session, QueryResponse, Message } from '../types';

export const sessionsMock: Session[] = [
  {
    talker_id: "mock_talker_002",
    display_name: "张经理",
    last_timestamp: 1707922800000,
    build_status: "complete",
    message_count: 125
  },
  {
    talker_id: "doctor_001",
    display_name: "李医生",
    last_timestamp: 1707800000000,
    build_status: "complete",
    message_count: 118
  },
  {
    talker_id: "teacher_001",
    display_name: "王老师",
    last_timestamp: 1707500000000,
    build_status: "complete",
    message_count: 132
  },
  {
    talker_id: "mock_talker_001",
    display_name: "TA",
    last_timestamp: 1707922800000,
    build_status: "complete",
    message_count: 129
  }
];

function generateWorkMessages(): Message[] {
  const messages: Message[] = [];
  let baseTime = 1704000000000; // Jan 1, 2024
  
  const fillers = [
    "收到", "好的", "没问题", "稍等我看一下", "文件发群里了", 
    "下午两点开个会对一下", "这个需求确认了吗？", "测试环境部署好了",
    "辛苦跟进一下", "我这边OK了", "今天有点卡", "API文档更新了",
    "前端联调一下", "UI走查还有几个问题", "下周一给反馈",
    "辛苦了", "收到，谢谢", "这个逻辑还要再确认下", "后端接口通了",
    "麻烦看下这个报错", "我晚点回复你", "先按这个方案走", "没问题，我来处理"
  ];

  for (let i = 1; i <= 125; i++) {
    baseTime += Math.floor(Math.random() * 20000000) + 3600000; // Add 1-6 hours
    const isSend = Math.random() > 0.5;
    messages.push({
      local_id: i,
      create_time: baseTime,
      is_send: isSend,
      sender_display: isSend ? "我" : "张经理",
      parsed_content: fillers[Math.floor(Math.random() * fillers.length)]
    });
  }

  // Inject Evidence for Phase 1 (Jan)
  messages[14] = { local_id: 15, create_time: 1704067200000, is_send: false, sender_display: "张经理", parsed_content: "小陈，Q1 重点是把 A 模块做出来，B 接口和下游联调也要跟上", phase_index: 1 };
  messages[21] = { local_id: 22, create_time: 1704153600000, is_send: true, sender_display: "我", parsed_content: "好的，A 模块我计划 1 月底前出初版", phase_index: 1 };
  messages[27] = { local_id: 28, create_time: 1704240000000, is_send: false, sender_display: "张经理", parsed_content: "行，有进展随时同步", phase_index: 1 };

  // Inject Evidence for Phase 2 (Feb)
  messages[64] = { local_id: 65, create_time: 1706745600000, is_send: true, sender_display: "我", parsed_content: "张经理，A 模块大概完成 70% 了，但 B 接口那边说他们还没准备好", phase_index: 2 };
  messages[69] = { local_id: 70, create_time: 1706832000000, is_send: false, sender_display: "张经理", parsed_content: "你先内部自测，B 接口等下游好了再说，别卡在这", phase_index: 2 };
  messages[74] = { local_id: 75, create_time: 1706918400000, is_send: false, sender_display: "张经理", parsed_content: "周五前把自测报告发我", phase_index: 2 };

  // Inject Evidence for Phase 3 (Mid Feb)
  messages[109] = { local_id: 110, create_time: 1707922800000, is_send: true, sender_display: "我", parsed_content: "自测报告已发，您看下", phase_index: 3 };
  messages[114] = { local_id: 115, create_time: 1707926400000, is_send: false, sender_display: "张经理", parsed_content: "整体不错，有几处小问题我标红了，你下周修一下", phase_index: 3 };
  messages[117] = { local_id: 118, create_time: 1707930000000, is_send: false, sender_display: "张经理", parsed_content: "修完提测，顺利的话 2 月底能上", phase_index: 3 };

  return messages;
}

export const workMessages = generateWorkMessages();

export const queryWorkMock: QueryResponse = {
  conversation_id: "conv_mock_work",
  question: "我们这个工作进展怎么样了？",
  phases: [
    {
      phase_index: 1,
      phase_title: "项目启动与任务分配",
      time_range: "2024年1月",
      core_conclusion: "张经理明确了 Q1 目标：完成 A 模块开发、B 接口联调。你承诺 1 月底前交付初版。",
      evidence: [
        { local_id: 15, create_time: 1704067200000, is_send: false, sender_display: "张经理", parsed_content: "小陈，Q1 重点是把 A 模块做出来，B 接口和下游联调也要跟上", phase_index: 1 },
        { local_id: 22, create_time: 1704153600000, is_send: true, sender_display: "我", parsed_content: "好的，A 模块我计划 1 月底前出初版", phase_index: 1 },
        { local_id: 28, create_time: 1704240000000, is_send: false, sender_display: "张经理", parsed_content: "行，有进展随时同步", phase_index: 1 }
      ],
      reasoning_chain: "任务分配 + 时间承诺 + 确认 → 项目启动阶段，目标清晰。",
      uncertainty_note: null,
      verified: true
    },
    {
      phase_index: 2,
      phase_title: "中期推进与阻塞",
      time_range: "2024年2月",
      core_conclusion: "A 模块开发完成 70%，但 B 接口联调因下游延期受阻。张经理要求先内部自测，等下游就绪再联调。",
      evidence: [
        { local_id: 65, create_time: 1706745600000, is_send: true, sender_display: "我", parsed_content: "张经理，A 模块大概完成 70% 了，但 B 接口那边说他们还没准备好", phase_index: 2 },
        { local_id: 70, create_time: 1706832000000, is_send: false, sender_display: "张经理", parsed_content: "你先内部自测，B 接口等下游好了再说，别卡在这", phase_index: 2 },
        { local_id: 75, create_time: 1706918400000, is_send: false, sender_display: "张经理", parsed_content: "周五前把自测报告发我", phase_index: 2 }
      ],
      reasoning_chain: "进度汇报 + 阻塞说明 + 经理调整策略 → 中期推进，有依赖但已明确应对。",
      uncertainty_note: "下游具体何时就绪未在对话中明确。",
      verified: true
    },
    {
      phase_index: 3,
      phase_title: "当前状态与下一步",
      time_range: "2024年2月中",
      core_conclusion: "自测已完成，张经理反馈「整体不错，有几处小问题」。要求下周修复后提测，预计 2 月底可上线。",
      evidence: [
        { local_id: 110, create_time: 1707922800000, is_send: true, sender_display: "我", parsed_content: "自测报告已发，您看下", phase_index: 3 },
        { local_id: 115, create_time: 1707926400000, is_send: false, sender_display: "张经理", parsed_content: "整体不错，有几处小问题我标红了，你下周修一下", phase_index: 3 },
        { local_id: 118, create_time: 1707930000000, is_send: false, sender_display: "张经理", parsed_content: "修完提测，顺利的话 2 月底能上", phase_index: 3 }
      ],
      reasoning_chain: "自测完成 + 经理反馈 + 时间节点 → 当前状态清晰，下一步明确。",
      uncertainty_note: null,
      verified: true
    }
  ],
  agent_trace: {
    steps: [
      {
        node_name: "planner",
        node_name_display: "意图解析",
        input_summary: "用户问题：我们这个工作进展怎么样了？",
        output_summary: "解析为 progress_summary，关注：任务、进度、反馈、时间节点",
        llm_calls: 1,
        timestamp_ms: 1707922810000
      },
      {
        node_name: "retriever",
        node_name_display: "检索锚点与节点",
        input_summary: "按任务/进度/反馈查询相关消息",
        output_summary: "命中任务分配、进度汇报、经理反馈等关键节点",
        llm_calls: 0,
        timestamp_ms: 1707922812000
      },
      {
        node_name: "grader",
        node_name_display: "证据评估",
        input_summary: "已收集节点，覆盖 2024.01 - 2024.02",
        output_summary: "信息充足，可生成进展摘要",
        llm_calls: 1,
        timestamp_ms: 1707922815000
      },
      {
        node_name: "generator",
        node_name_display: "叙事生成",
        input_summary: "节点摘要 + 消息预览",
        output_summary: "生成 3 个阶段（启动、中期、当前），证据验证通过",
        llm_calls: 1,
        timestamp_ms: 1707922820000
      }
    ],
    total_llm_calls: 3,
    total_duration_ms: 10000
  },
  all_messages: generateWorkMessages()
};
