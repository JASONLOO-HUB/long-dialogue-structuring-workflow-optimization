# 数据存储与持久化

## 本地存储与索引实现方案
为实现应用的高性能、快速冷启动和数据持久化，采用基于 IndexedDB 的本地存储架构，并结合双层缓存策略进行优化。

### IndexedDB本地存储架构与优化

#### **架构概览：双层异构存储**
为平衡冷启动速度与内容完整性，数据被拆分为轻量级关系数据和重量级非结构化数据，存储于两个不同的逻辑层。

-   **Tier 1: 骨架层 (Skeleton Layer)**
    -   **存储技术**: IndexedDB (Object Store)。
    -   **数据类型**: JSON 树状结构，包含节点的元数据和关系。
    -   **核心职责**: 驱动全景知识地图、顶部缩略图和SOP（标准操作程序）的瞬间渲染。此层数据体积小（< 1MB），读写频率极高。

-   **Tier 2: 肌肉层 (Muscle Layer)**
    -   **存储技术**: IndexedDB (Key-Value)。
    -   **数据类型**: Blob / 文本流，存储每个节点的完整对话记录、代码块、数学公式等。
    -   **核心职责**: 按需填充对话窗口的内容。此层数据体积较大（可达数十MB），读取频率较低。

-   **技术选型**:
    -   推荐使用 `Dexie.js` 或 `idb` 等库对原生 IndexedDB API 进行封装，以简化事务管理和异步操作。

#### **数据库Schema设计**
定义两个核心的 Object Store：`SessionGraph`（骨架层）和 `NodeContent`（肌肉层）。

-   **`SessionGraph` Store (骨架层)**
    -   **结构**: 以 Session ID 为主键，存储整个知识树对象。
    -   **节点元数据 (`NodeMeta`) 接口**:
        -   `id`: 节点的唯一标识符。
        -   `parentId`: 指向父节点，用于构建树状关系。
        -   `title`: 节点标题，用于地图展示。
        -   `summary`: AI自动生成的百字摘要，用于快速预览和记忆恢复。
        -   `depth`: 节点的层级深度（L1, L2, ...）。
        -   `status`: 节点状态（如 `locked`, `active`, `completed`）。
        -   `seeds`: 缓存的AI建议，包括 `parallel` (平行扩展) 和 `diveIn` (深度钻研) 两种。
        -   `timestamps`: 记录节点的创建和最后访问时间。

-   **`NodeContent` Store (肌肉层)**
    -   **结构**: 以 `nodeId` 为主键，存储每个节点的详细内容。
    -   **内容 (`NodeContent`) 接口**:
        -   `nodeId`: 关联到 `SessionGraph` 中的节点ID。
        -   `messages`: 一个数组，包含该节点的所有对话记录。每条记录包括：
            -   `role`: `user`, `ai`, 或 `system`。
            -   `content`: 完整的 Markdown 源码。
            -   `timestamp`: 消息时间戳。
            -   `meta`: 可选元数据，如 `tokenCount`。

#### **关键性能优化：写入缓冲池**
为避免AI流式输出高频写入数据库导致的UI卡顿，设计一个内存写入缓冲池。

-   **流式接收**: AI生成的Token首先暂存在前端内存变量中，用于实时驱动UI渲染。
-   **防抖写入 (Debounced Flush)**: 仅当缓冲区积累了一定量的文本，或AI输出暂停时（例如，设置2秒的定时器或检测到句号），才触发一次数据库的批量写入操作。
-   **异常保护**: 监听浏览器的 `beforeunload` 事件，在用户关闭页面前，强制执行一次同步的 `flush` 操作，将内存中的数据写入IndexedDB，防止数据丢失。

#### **冷启动加速方案：索引与预加载**
-   **复合索引**: 在 `NodeContent` 表中建立 `[sessionId + lastAccessed]` 的复合索引，为未来实现“最近常看的节点”等功能提供高效查询基础。
-   **视口预判算法**: 利用浏览器的空闲时间 (`requestIdleCallback`) 进行静默预加载，实现秒开体验。
    1.  **T0 (初始)**: 加载并渲染 `SessionGraph` 骨架层，瞬间展示知识地图。
    2.  **T+100ms (视口)**: 立刻加载当前激活节点及其父节点的内容，填充主工作区。
    3.  **Idle Time (空闲)**: 在后台计算并预加载当前节点的“邻居节点”（如兄弟节点、子节点）的内容，并将其缓存到内存中（如 LRU Cache），实现用户在节点间跳转时的瞬时加载。

#### **数据安全与导出格式**
-   **数据隔离**: IndexedDB遵循浏览器同源策略，天然具备数据隔离能力，防止其他网站访问。
-   **文件导出格式**:
    -   **打包**: 导出时，将 `SessionGraph` 和所有相关的 `NodeContent` 打包成一个`.mind`文件。
    -   **压缩**: 使用 `pako` (zlib 的 JavaScript 移植版) 等库对导出的JSON字符串进行压缩，可显著减小文件体积（约70%）。
    -   **加密 (可选)**: 提供隐私模式，在导出前使用 AES-GCM 对敏感内容字段进行加密，密钥由用户密码生成。

#### **代码层面的实现伪代码**
以下是基于 `Dexie.js` 的实现范例，用于展示数据库定义和写入缓冲区的核心逻辑。

```typescript
import Dexie from 'dexie';

// 定义数据库结构
class MindWeaveDB extends Dexie {
  sessions: Dexie.Table<SessionMeta, string>; // session_uuid as key
  content: Dexie.Table<NodeContent, string>;  // nodeId as key

  constructor() {
    super('MindWeaveDatabase');
    this.version(1).stores({
      sessions: 'id, lastAccessed',
      content: 'nodeId'
    });
  }
}

const db = new MindWeaveDB();

// 写入优化：防抖保存逻辑
let writeBuffer = {};
let timer = null;

function streamToBuffer(nodeId: string, chunk: string) {
  // 1. 更新内存 (UI 立即反应)
  if (!writeBuffer[nodeId]) writeBuffer[nodeId] = "";
  writeBuffer[nodeId] += chunk;

  // 2. 防抖写入 DB
  clearTimeout(timer);
  timer = setTimeout(() => {
    // 假设 getFullLogFromMemory() 从内存获取完整日志
    db.content.put({ nodeId, messages: getFullLogFromMemory(nodeId) });
  }, 2000); // 2秒写一次磁盘
}
```