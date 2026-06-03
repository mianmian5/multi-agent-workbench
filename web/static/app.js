/* Multi-Agent Workbench - 前端交互逻辑 v3 */

let currentTaskId = null;
let timerInterval = null;
let startTime = null;

const AGENT_ICONS = {
    '搜索专员': '🔍', '写作专员': '✍️',
    '总结专员': '📋', '讨论专员': '💬',
    '编程专员': '💻', '翻译专员': '🌐',
};

const AGENT_COLORS = {
    '搜索专员': '#74b9ff', '写作专员': '#fd79a8',
    '总结专员': '#55efc4', '讨论专员': '#fdcb6e',
    '编程专员': '#a29bfe', '翻译专员': '#fab1a0',
};

// ===== 主题 =====
function initTheme() {
    const saved = localStorage.getItem('awb-theme') || 'light';
    document.documentElement.setAttribute('data-theme', saved);
    document.getElementById('themeToggle').textContent = saved === 'dark' ? '🌙' : '☀️';
}

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('awb-theme', next);
    document.getElementById('themeToggle').textContent = next === 'dark' ? '🌙' : '☀️';
}

// ===== 侧边栏 =====
function toggleSidebar() {
    document.getElementById('sidebar').classList.toggle('open');
    if (document.getElementById('sidebar').classList.contains('open')) {
        loadHistory();
    }
    document.getElementById('sidebarMask').classList.toggle('show');
}

function closeSidebarOutside(event) {
    if (event.target === document.getElementById('sidebarMask')) {
        toggleSidebar();
    }
}

function loadHistory() {
    fetch('/mawb/api/history')
        .then(r => r.json())
        .then(data => {
            const list = document.getElementById('historyList');
            if (data.length === 0) {
                list.innerHTML = '<div class="history-empty">暂无记录</div>';
                return;
            }
            list.innerHTML = data.map(h =>
                `<div class="history-item" onclick="loadHistoryDetail('${h.id}')">
                    <div class="h-time">${h.time || ''} · ${h.duration || 0}s</div>
                    <div class="h-task">${h.title || h.task}</div>
                </div>`
            ).join('');
        });
}

function loadHistoryDetail(id) {
    // 关闭侧边栏和遮罩
    document.getElementById('sidebar').classList.remove('open');
    document.getElementById('sidebarMask').classList.remove('show');

    fetch(`/mawb/api/history/${id}`)
        .then(r => r.json())
        .then(data => {
            document.getElementById('workArea').style.display = 'block';
            document.getElementById('resultSection').style.display = 'block';
            const resultHtml = marked.parse(data.result || '');
            document.getElementById('resultContent').innerHTML = resultHtml;
            document.getElementById('resultContent').dataset.rawMarkdown = data.result || '';
            document.getElementById('statusBadge').className = 'status-badge done';
            document.getElementById('statusBadge').textContent = '✅ 已完成';
            document.getElementById('taskInput').value = data.task || '';
            document.getElementById('stepsContainer').innerHTML = '';
            document.getElementById('discussSection').style.display = 'none';
            document.getElementById('logContainer').innerHTML = '<div class="log-entry">📂 加载历史记录</div>';
            document.getElementById('timer').textContent = `⏱ ${data.duration || 0}s`;
        });
}

// ===== 任务模板 =====
function loadTemplates() {
    fetch('/mawb/api/templates')
        .then(r => r.json())
        .then(templates => {
            const container = document.getElementById('templateGrid');
            container.innerHTML = templates.map(t => `
                <div class="template-card" onclick="applyTemplate('${t.id}')">
                    <div class="template-title">${t.title}</div>
                    <div class="template-desc">${t.desc}</div>
                </div>
            `).join('');
        });
}

function applyTemplate(templateId) {
    fetch('/mawb/api/templates')
        .then(r => r.json())
        .then(templates => {
            const t = templates.find(t => t.id === templateId);
            if (t) {
                document.getElementById('taskInput').value = t.task;
                document.getElementById('taskInput').focus();
            }
            // 自由模式就清空输入框
            if (templateId === 'free') {
                document.getElementById('taskInput').value = '';
                document.getElementById('taskInput').focus();
            }
        });
}

// ===== 运行任务 =====
let taskFiles = [];  // 对话中上传的附件

function initTaskFileUpload() {
    const input = document.getElementById('taskFileInput');
    input.addEventListener('change', () => {
        if (input.files.length > 0) {
            addTaskFiles(input.files);
            input.value = '';
        }
    });
}

function addTaskFiles(files) {
    Array.from(files).forEach(file => {
        // 只读文本类文件
        if (!file.name.match(/\.(txt|md|csv|pdf)$/i)) {
            alert(`不支持的文件类型: ${file.name}`);
            return;
        }
        const reader = new FileReader();
        reader.onload = function(e) {
            taskFiles.push({
                name: file.name,
                content: e.target.result,
            });
            renderFileTags();
        };
        reader.readAsText(file);
    });
}

function removeTaskFile(index) {
    taskFiles.splice(index, 1);
    renderFileTags();
}

function renderFileTags() {
    const container = document.getElementById('fileAttachments');
    if (taskFiles.length === 0) {
        container.innerHTML = '';
        return;
    }
    container.innerHTML = taskFiles.map((f, i) =>
        `<span class="file-tag">📄 ${escHtml(f.name)} <span class="file-tag-remove" onclick="removeTaskFile(${i})">✕</span></span>`
    ).join('');
}

function runTask() {
    const input = document.getElementById('taskInput');
    const task = input.value.trim();
    if (!task) { input.focus(); return; }

    const btn = document.getElementById('runBtn');
    btn.disabled = true;
    btn.querySelector('.btn-text').textContent = '执行中...';

    document.getElementById('workArea').style.display = 'block';
    document.getElementById('stepsContainer').innerHTML = '';
    document.getElementById('discussContainer').innerHTML = '';
    document.getElementById('discussSection').style.display = 'none';
    document.getElementById('logContainer').innerHTML = '';
    document.getElementById('resultSection').style.display = 'none';
    document.getElementById('resultContent').textContent = '';
    document.getElementById('templateSection').style.display = 'none';
    updateStatus('running');
    startTimer();

    const discussEnabled = document.getElementById('discussCheck').checked;
    const files = taskFiles.map(f => ({ name: f.name, content: f.content.slice(0, 5000) }));

    fetch('/mawb/api/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task, files, discuss: discussEnabled }),
    })
    .then(r => r.json())
    .then(data => {
        currentTaskId = data.task_id;
        connectSSE(data.task_id);
    })
    .catch(err => {
        addLog('系统', '❌ ' + err.message);
        updateStatus('error');
        stopTimer();
        enableBtn();
    });
}

// ===== SSE =====
function connectSSE(taskId) {
    const source = new EventSource(`/mawb/api/stream/${taskId}`);

    source.onmessage = function(event) {
        try {
            const data = JSON.parse(event.data);
            handleEvent(data);
        } catch(e) {}
    };

    source.onerror = function() {
        source.close();
        if (document.getElementById('statusBadge').classList.contains('running')) {
            setTimeout(() => connectSSE(currentTaskId), 2000);
        }
    };
}

function handleEvent(data) {
    switch (data.type) {
        case 'planning':
            addLog('系统', '📐 正在拆解任务...');
            break;
        case 'plan':
            renderSteps(data.steps);
            addLog('系统', `📋 任务拆解完成，共 ${data.steps.length} 个步骤`);
            break;
        case 'executing':
            addLog('系统', '🚀 开始执行...');
            break;
        case 'step_start':
            updateStepStatus(data.step, 'active');
            addLog(data.agent, `▶️ 开始: ${data.task}`);
            // 显示子查询
            if (data.sub_queries && data.sub_queries.length > 0) {
                const el = document.getElementById(`subqueries-${data.step}`);
                if (el) {
                    el.innerHTML = `<div style="font-size:11px;color:var(--text-sec);margin-top:4px;padding:4px 8px;background:var(--surface-2);border-radius:4px;">🔍 搜索方向: ${data.sub_queries.join(" | ")}</div>`;
                    el.style.display = 'block';
                }
            }
            break;
        case 'step_done':
            updateStepStatus(data.step, 'done');
            showStepPreview(data.step, data.result_preview);
            addLog(data.agent, '✅ 完成');
            break;
        case 'step_error':
            updateStepStatus(data.step, 'error');
            addLog(data.agent, `❌ 错误: ${data.error}`);
            break;
        case 'discuss_start':
            document.getElementById('discussSection').style.display = 'block';
            const roundInfo = data.round ? `第${data.round}轮` : '';
            addLog('系统', `💬 ${roundInfo} ${data.message || '讨论阶段开始...'}`);
            break;
        case 'discuss_context':
            addLog('主持人', `📋 讨论要点: ${(data.context || '').slice(0, 80)}...`);
            addDiscussBubble('📋 主持人', `📋 **本轮讨论要点:** ${data.context || ''}`, false);
            break;
        case 'discuss_feedback':
            const roundTag = data.round ? `[第${data.round}轮] ` : '';
            if (data.status === 'thinking') {
                addDiscussBubble(data.agent, `${roundTag}⏳ 正在审阅...`, true);
            } else if (data.status === 'error') {
                addDiscussBubble(data.agent, `${roundTag}❌ 审阅出错`, false);
            } else {
                addDiscussBubble(data.agent, `${roundTag}${data.feedback || '✅ 审阅完毕'}`, false);
                addLog(data.agent, `💬 ${roundTag}审阅: ${(data.feedback || '').slice(0, 60)}...`);
            }
            break;
        case 'discuss_summary':
            addLog('讨论专员', `📋 讨论总结: ${data.summary.slice(0, 100)}...`);
            addDiscussBubble('📋 总结', data.summary, false);
            break;
        case 'broadcast':
            addLog(data.agent, data.content);
            break;
        case 'completed':
            updateStatus('done');
            stopTimer();
            showResult(data.result, true);
            addLog('系统', `✅ 全部完成！耗时 ${data.duration} 秒`);
            enableBtn();
            loadHistory();
            break;
        case 'error':
            updateStatus('error');
            stopTimer();
            addLog('系统', `❌ ${data.message}`);
            enableBtn();
            break;
    }
}

// ===== 渲染步骤 =====
function renderSteps(steps) {
    const container = document.getElementById('stepsContainer');
    container.innerHTML = '';

    steps.forEach((step, i) => {
        if (i > 0) {
            const c = document.createElement('div');
            c.className = 'step-connector'; c.innerHTML = '⬇';
            container.appendChild(c);
        }

        const card = document.createElement('div');
        card.className = 'step-card';
        card.id = `step-${step.step}`;

        const icon = AGENT_ICONS[step.agent] || '🤖';
        const color = AGENT_COLORS[step.agent] || 'var(--text)';

        card.innerHTML = `
            <div class="step-header">
                <div class="step-number">${step.step}</div>
                <span class="agent-icon">${icon}</span>
                <span class="agent-name" style="color:${color}">${step.agent}</span>
                <span class="step-status" id="status-${step.step}">⏳ 等待中</span>
            </div>
            <div class="step-task">${step.task}</div>
            <div class="step-subqueries" id="subqueries-${step.step}" style="display:none;"></div>
                <div class="step-result-preview" id="preview-${step.step}" style="display:none;"></div>
        `;
        container.appendChild(card);
    });
}

function updateStepStatus(stepNum, status) {
    const card = document.getElementById(`step-${stepNum}`);
    if (!card) return;
    card.classList.remove('active', 'done', 'error');
    const statusEl = document.getElementById(`status-${stepNum}`);
    const texts = { 'active': '⏳ 执行中...', 'done': '✅ 已完成', 'error': '❌ 失败' };
    card.classList.add(status);
    statusEl.textContent = texts[status] || status;
}

function showStepPreview(stepNum, preview) {
    const el = document.getElementById(`preview-${stepNum}`);
    if (el) {
        try {
            el.innerHTML = marked.parse(preview);
        } catch(e) {
            el.textContent = preview;
        }
        el.style.display = 'block';
    }
}

// ===== 讨论气泡 =====
function addDiscussBubble(agent, text, thinking) {
    const container = document.getElementById('discussContainer');
    const bubble = document.createElement('div');
    bubble.className = 'discuss-bubble';

    const icon = AGENT_ICONS[agent] || '🤖';
    const color = AGENT_COLORS[agent] || 'var(--accent)';

    // 渲染 Markdown（非 thinking 状态，且文本不超长）
    const renderMd = !thinking && text;  // render markdown for all non-thinking text
    const displayHtml = renderMd ? marked.parse(text) : escHtml(text);

    if (agent === '📋 总结') {
        bubble.innerHTML = `
            <div class="bubble-avatar" style="background:var(--accent)22; color:var(--accent)">📋</div>
            <div class="bubble-content">
                <div class="bubble-name" style="color:var(--accent)">📋 主持人总结</div>
                <div class="bubble-text" style="font-weight:500">${displayHtml}</div>
            </div>
        `;
    } else {
        bubble.innerHTML = `
            <div class="bubble-avatar" style="background:${color}22; color:${color}">${icon}</div>
            <div class="bubble-content">
                <div class="bubble-name" style="color:${color}">${agent}</div>
                <div class="${thinking ? 'bubble-thinking' : 'bubble-text'}">${displayHtml}</div>
            </div>
        `;
    }

    container.appendChild(bubble);
    container.scrollTop = container.scrollHeight;
}

// ===== 结果 =====
function showResult(text, typewriter = false) {
    const section = document.getElementById('resultSection');
    const content = document.getElementById('resultContent');
    // 保存原始 Markdown 文本，供下载使用
    content.dataset.rawMarkdown = text;
    section.style.display = 'block';

    if (typewriter && text.length > 50) {
        // 打字机效果
        content.innerHTML = '<div class="typing-cursor">▌</div>';
        let index = 0;
        const chunkSize = 3;
        function typeNext() {
            if (index >= text.length) {
                // 最终渲染
                content.innerHTML = marked.parse(text);
                return;
            }
            index = Math.min(index + chunkSize, text.length);
            const partial = text.slice(0, index);
            try {
                content.innerHTML = marked.parse(partial) + '<div class="typing-cursor">▌</div>';
            } catch(e) {
                content.innerHTML = partial.replace(/\n/g, '<br>') + '<div class="typing-cursor">▌</div>';
            }
            requestAnimationFrame(typeNext);
        }
        requestAnimationFrame(typeNext);
    } else {
        // 直接显示
        const html = marked.parse(text);
        content.innerHTML = html;
    }
}

function copyResult() {
    const text = getRawMarkdown();
    navigator.clipboard.writeText(text).then(() => {
        const btn = document.querySelector('.result-header .icon-btn');
        if (btn) {
            const icons = btn.parentElement.querySelectorAll('.icon-btn');
            const copyBtn = icons[0];
            if (copyBtn) {
                copyBtn.textContent = '✅';
                setTimeout(() => copyBtn.textContent = '📋', 1500);
            }
        }
    });
}

// ===== 日志 =====
function addLog(sender, message) {
    const container = document.getElementById('logContainer');
    const entry = document.createElement('div');
    entry.className = 'log-entry';
    entry.innerHTML = `
        <span class="log-time">${new Date().toLocaleTimeString()}</span>
        <span class="log-agent">[${sender}]</span>
        <span class="log-arrow">▸</span>
        <span>${message}</span>
    `;
    container.appendChild(entry);
    container.scrollTop = container.scrollHeight;
}

// ===== 状态 =====
function updateStatus(status) {
    const badge = document.getElementById('statusBadge');
    badge.className = 'status-badge';
    badge.classList.add(status);
    badge.textContent = {
        'running': '⏳ 执行中',
        'done': '✅ 已完成',
        'error': '❌ 出错了',
        'waiting': '⏸ 等待中',
    }[status] || status;
}

function startTimer() {
    startTime = Date.now();
    timerInterval = setInterval(() => {
        document.getElementById('timer').textContent =
            `⏱ ${Math.floor((Date.now() - startTime) / 1000)}s`;
    }, 200);
}

function stopTimer() {
    if (timerInterval) { clearInterval(timerInterval); timerInterval = null; }
}

function enableBtn() {
    const btn = document.getElementById('runBtn');
    btn.disabled = false;
    btn.querySelector('.btn-text').textContent = '再来一次';
    // 显示模板区域
    document.getElementById('templateSection').style.display = 'block';
}

// ===== 初始化 =====
initTheme();

// ===== 设置 =====
function updateModelSelect() {
    const sel = document.getElementById('setModel');
    const custom = document.getElementById('setModelCustom');
    if (sel.value === '__custom__') {
        custom.style.display = 'block';
        custom.focus();
    } else {
        custom.style.display = 'none';
    }
}

document.addEventListener('DOMContentLoaded', function() {
    document.getElementById('setModel').addEventListener('change', updateModelSelect);
    loadTemplates();
});

function toggleSettings() {
    const modal = document.getElementById('settingsModal');
    const isOpen = modal.style.display !== 'none';
    modal.style.display = isOpen ? 'none' : 'flex';
    if (!isOpen) loadSettings();
}

function closeSettingsOutside(event) {
    if (event.target === event.currentTarget) toggleSettings();
}

function loadSettings() {
    fetch('/mawb/api/settings')
        .then(r => r.json())
        .then(data => {
            if (data.llm_key_prefix) {
                document.getElementById('currentKeyHint').textContent = data.llm_key_prefix;
                document.getElementById('footerModel').textContent = data.llm_model || '⚙️ 配置 API';
            }
            if (data.llm_base_url) document.getElementById('setBaseUrl').value = data.llm_base_url;
            if (data.llm_model) {
                const sel = document.getElementById('setModel');
                const options = Array.from(sel.options);
                const match = options.find(o => o.value === data.llm_model);
                if (match) {
                    sel.value = data.llm_model;
                } else {
                    sel.value = '__custom__';
                    document.getElementById('setModelCustom').value = data.llm_model;
                    document.getElementById('setModelCustom').style.display = 'block';
                }
            }
        });
}

function saveSettings() {
    const apiKey = document.getElementById('setApiKey').value.trim();
    const baseUrl = document.getElementById('setBaseUrl').value.trim();
    let model = document.getElementById('setModel').value;
    if (model === '__custom__') {
        model = document.getElementById('setModelCustom').value.trim();
        if (!model) { alert('请输入自定义模型名称'); return; }
    }

    const body = {};
    if (apiKey) body.api_key = apiKey;
    if (baseUrl) body.base_url = baseUrl;
    body.model = model;

    const status = document.getElementById('settingsStatus');
    status.textContent = '⏳ 保存中...';

    fetch('/mawb/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    })
    .then(r => r.json())
    .then(data => {
        status.textContent = data.message || '✅ 已保存！';
        setTimeout(() => status.textContent = '', 3000);
        document.getElementById('footerModel').textContent = model;
        // 清空 API Key 输入框（安全）
        if (apiKey) document.getElementById('setApiKey').value = '';
        // 刷新显示
        loadSettings();
    })
    .catch(() => {
        status.textContent = '❌ 保存失败';
    });
}

function toggleKnowledge() {
    const modal = document.getElementById('knowledgeModal');
    const isOpen = modal.style.display !== 'none';
    modal.style.display = isOpen ? 'none' : 'flex';
    if (!isOpen) loadKnowledgeFiles();
}

function closeKnowledgeOutside(event) {
    if (event.target === event.currentTarget) toggleKnowledge();
}

function loadKnowledgeFiles() {
    fetch('/mawb/api/knowledge')
        .then(r => r.json())
        .then(files => {
            const list = document.getElementById('kbFileList');
            if (files.length === 0) {
                list.innerHTML = '<div class="kb-empty">暂无文件，上传文档让 Agent 在协作时使用 🚀</div>';
                document.getElementById('kbStats').textContent = '';
                return;
            }

            const stats = files.reduce((s, f) => ({ chunks: s.chunks + (f.chunks || 0), size: s.size + (f.size || 0) }), { chunks: 0, size: 0 });
            document.getElementById('kbStats').textContent = `共 ${files.length} 个文件，${stats.chunks} 个片段`;

            list.innerHTML = files.map(f => `
                <div class="kb-file-item">
                    <div class="kb-file-info">
                        <span class="kb-file-icon">${getFileIcon(f.type)}</span>
                        <span class="kb-file-name">${escHtml(f.name)}</span>
                    </div>
                    <div class="kb-file-meta">
                        ${f.chunks || 0} 段 · ${formatSize(f.size)}
                        <button class="kb-file-delete" onclick="deleteKnowledgeFile('${f.id}')">✕</button>
                    </div>
                </div>
            `).join('');
        });

    // 加载统计
    fetch('/mawb/api/knowledge/stats')
        .then(r => r.json())
        .then(stats => {
            const btn = document.querySelector('[title="知识库"]');
            if (btn && stats.file_count > 0) {
                btn.textContent = `📚 ${stats.file_count}`;
            }
        });
}

function getFileIcon(type) {
    const icons = { '.pdf': '📕', '.txt': '📄', '.md': '📝', '.csv': '📊' };
    return icons[type] || '📄';
}

function formatSize(bytes) {
    if (bytes < 1024) return `${bytes}B`;
    return `${(bytes / 1024).toFixed(1)}KB`;
}

function escHtml(s) {
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
}

// 文件上传
function setupFileUpload() {
    const area = document.getElementById('kbUploadArea');
    const input = document.getElementById('kbFileInput');

    // 点击上传
    area.addEventListener('click', () => input.click());

    // 选择文件
    input.addEventListener('change', () => {
        if (input.files.length > 0) uploadFiles(input.files);
    });

    // 拖拽上传
    area.addEventListener('dragover', (e) => {
        e.preventDefault();
        area.style.borderColor = 'var(--accent)';
        area.style.background = 'var(--card-hover)';
    });

    area.addEventListener('dragleave', () => {
        area.style.borderColor = '';
        area.style.background = '';
    });

    area.addEventListener('drop', (e) => {
        e.preventDefault();
        area.style.borderColor = '';
        area.style.background = '';
        if (e.dataTransfer.files.length > 0) uploadFiles(e.dataTransfer.files);
    });
}

function uploadFiles(files) {
    const status = document.getElementById('kbUploadStatus');
    const total = files.length;
    let done = 0;

    Array.from(files).forEach(file => {
        const formData = new FormData();
        formData.append('file', file);

        status.innerHTML = `⏳ 正在上传 ${file.name}...`;
        status.className = 'kb-upload-progress';

        fetch('/mawb/api/knowledge/upload', {
            method: 'POST',
            body: formData,
        })
        .then(r => r.json())
        .then(result => {
            done++;
            if (result.error) {
                status.innerHTML = `❌ ${file.name}: ${result.error}`;
                status.className = 'kb-upload-status';
            } else {
                status.innerHTML = `✅ ${file.name} 上传成功（${result.chunks} 个片段）`;
                status.className = 'kb-upload-status';
                if (done >= total) {
                    setTimeout(() => { status.innerHTML = ''; }, 2000);
                    loadKnowledgeFiles();
                }
            }
        })
        .catch(err => {
            done++;
            status.innerHTML = `❌ ${file.name}: 上传失败`;
            status.className = 'kb-upload-status';
        });
    });
}

function deleteKnowledgeFile(fileId) {
    if (!confirm('确定要删除此文件吗？')) return;
    fetch(`/mawb/api/knowledge/${fileId}`, { method: 'DELETE' })
        .then(r => r.json())
        .then(() => {
            loadKnowledgeFiles();
        });
}

// ===== 自定义 Agent =====
function toggleAgents() {
    const modal = document.getElementById('agentsModal');
    const isOpen = modal.style.display !== 'none';
    modal.style.display = isOpen ? 'none' : 'flex';
    if (!isOpen) loadAgents();
}

function closeAgentsOutside(event) {
    if (event.target === event.currentTarget) toggleAgents();
}

function loadAgents() {
    fetch('/mawb/api/agents/custom')
        .then(r => r.json())
        .then(agents => {
            const list = document.getElementById('agentsList');
            if (agents.length === 0) {
                list.innerHTML = '<div class="agents-empty">暂无自定义 Agent。创建一个试试！</div>';
                return;
            }
            list.innerHTML = agents.map(a => `
                <div class="agent-item">
                    <div class="agent-item-info">
                        <div class="agent-item-name">${escHtml(a.name)}</div>
                        <div class="agent-item-desc">${escHtml(a.description || '无描述')}</div>
                        <div class="agent-item-caps">
                            ${(a.capabilities || []).map(c => `<span>${escHtml(c)}</span>`).join('')}
                        </div>
                    </div>
                    <div class="agent-item-actions">
                        <button class="agent-edit-btn" onclick="editAgent('${a.id}')" title="编辑">✏️</button>
                        <button class="agent-delete-btn" onclick="deleteAgent('${a.id}')" title="删除">🗑️</button>
                    </div>
                </div>
            `).join('');

            // 更新角标
            const btn = document.querySelector('[title="自定义 Agent"]');
            if (btn && agents.length > 0) {
                btn.textContent = `🧩 ${agents.length}`;
            } else if (btn) {
                btn.textContent = '🧩';
            }
        });
}

function resetAgentForm() {
    document.getElementById('agentEditId').value = '';
    document.getElementById('agentName').value = '';
    document.getElementById('agentDesc').value = '';
    document.getElementById('agentCaps').value = '';
    document.getElementById('agentPrompt').value = '';
    document.getElementById('agentFormStatus').textContent = '';
}

function saveAgent() {
    const editId = document.getElementById('agentEditId').value;
    const name = document.getElementById('agentName').value.trim();
    const desc = document.getElementById('agentDesc').value.trim();
    const caps = document.getElementById('agentCaps').value.trim();
    const prompt = document.getElementById('agentPrompt').value.trim();

    if (!name) { alert('请输入 Agent 名称'); return; }
    if (!prompt) { alert('请输入系统提示词'); return; }

    const body = { name, description: desc, capabilities: caps, system_prompt: prompt };
    const status = document.getElementById('agentFormStatus');

    const url = editId ? `/mawb/api/agents/custom/${editId}` : '/mawb/api/agents/custom';
    const method = editId ? 'PUT' : 'POST';

    status.textContent = '⏳ 保存中...';

    fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
        .then(r => r.json())
        .then(data => {
            if (data.error) {
                status.textContent = `❌ ${data.error}`;
                return;
            }
            status.textContent = '✅ 保存成功！服务重启后生效';
            resetAgentForm();
            loadAgents();
            setTimeout(() => status.textContent = '', 3000);
        })
        .catch(() => { status.textContent = '❌ 保存失败'; });
}

function editAgent(agentId) {
    fetch('/mawb/api/agents/custom')
        .then(r => r.json())
        .then(agents => {
            const agent = agents.find(a => a.id === agentId);
            if (!agent) return;
            document.getElementById('agentEditId').value = agent.id;
            document.getElementById('agentName').value = agent.name;
            document.getElementById('agentDesc').value = agent.description || '';
            document.getElementById('agentCaps').value = (agent.capabilities || []).join(', ');
            document.getElementById('agentPrompt').value = agent.system_prompt || '';
            document.getElementById('agentFormStatus').textContent = '✏️ 编辑模式';
        });
}

function deleteAgent(agentId) {
    if (!confirm('确定要删除这个自定义 Agent 吗？')) return;
    fetch(`/mawb/api/agents/custom/${agentId}`, { method: 'DELETE' })
        .then(r => r.json())
        .then(() => { loadAgents(); });
}

// ===== 记忆系统 =====
function toggleMemory() {
    const modal = document.getElementById('memoryModal');
    const isOpen = modal.style.display !== 'none';
    modal.style.display = isOpen ? 'none' : 'flex';
    if (!isOpen) loadMemory();
}

function closeMemoryOutside(event) {
    if (event.target === event.currentTarget) toggleMemory();
}

function loadMemory() {
    fetch('/mawb/api/memory?limit=100')
        .then(r => r.json())
        .then(memories => {
            const list = document.getElementById('memList');
            if (memories.length === 0) {
                list.innerHTML = '<div class="mem-empty">暂无记忆。完成任务后 Agent 会自动创建记忆 🧠</div>';
                document.getElementById('memStats').textContent = '';
                return;
            }
            renderMemories(memories);
        });

    fetch('/mawb/api/memory/stats')
        .then(r => r.json())
        .then(stats => {
            document.getElementById('memStats').textContent = `共 ${stats.total} 条`;
            const btn = document.querySelector('[title="记忆系统"]');
            if (btn && stats.total > 0) {
                btn.textContent = `🧠 ${stats.total}`;
            } else if (btn) {
                btn.textContent = '🧠';
            }
        });
}

function renderMemories(memories) {
    const list = document.getElementById('memList');
    const icons = { 'fact': '📌', 'preference': '❤️', 'summary': '📝', 'note': '💡' };
    list.innerHTML = memories.map(m => `
        <div class="mem-item">
            <div class="mem-item-icon">${icons[m.type] || '💡'}</div>
            <div class="mem-item-body">
                <div class="mem-item-content">${escHtml(m.summary || m.content || '')}</div>
                <div class="mem-item-meta">
                    <span>${m.type}</span>
                    ${(m.tags || []).map(t => `<span>${escHtml(t)}</span>`).join('')}
                    <span>${m.created_at || ''}</span>
                </div>
            </div>
            <button class="mem-item-delete" onclick="deleteMemory('${m.id}')">✕</button>
        </div>
    `).join('');
}

function searchMemory(query) {
    if (!query.trim()) {
        loadMemory();
        return;
    }
    fetch(`/mawb/api/memory/search?query=${encodeURIComponent(query)}`)
        .then(r => r.json())
        .then(memories => {
            if (memories.length === 0) {
                document.getElementById('memList').innerHTML = '<div class="mem-empty">未找到匹配的记忆</div>';
            } else {
                renderMemories(memories.map(m => ({
                    id: m.id, type: m.type,
                    summary: m.content.slice(0, 80),
                    tags: m.tags, created_at: m.created_at
                })));
            }
        });
}

function addMemory() {
    const content = document.getElementById('memInput').value.trim();
    const type = document.getElementById('memType').value;
    const tags = document.getElementById('memTags').value.split(/[,，]/).map(t => t.trim()).filter(Boolean);
    if (!content) { return; }

    const status = document.getElementById('memFormStatus');
    fetch('/mawb/api/memory', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content, type, tags }),
    })
    .then(r => r.json())
    .then(() => {
        document.getElementById('memInput').value = '';
        document.getElementById('memTags').value = '';
        status.textContent = '✅ 已保存';
        setTimeout(() => status.textContent = '', 2000);
        loadMemory();
    })
    .catch(() => { status.textContent = '❌ 保存失败'; });
}

function deleteMemory(memId) {
    if (!confirm('确定删除这条记忆？')) return;
    fetch(`/mawb/api/memory/${memId}`, { method: 'DELETE' })
        .then(() => loadMemory());
}

// ===== 下载增强 =====
function toggleDownloadMenu() {
    document.getElementById('downloadDropdown').classList.toggle('show');
}

// 点击其他地方关闭下载菜单
document.addEventListener('click', function(e) {
    const dd = document.getElementById('downloadDropdown');
    if (dd && dd.classList.contains('show') && !e.target.closest('.download-menu')) {
        dd.classList.remove('show');
    }
});

function getRawMarkdown() {
    // 优先用保存的原始 Markdown
    const el = document.getElementById('resultContent');
    return el.dataset.rawMarkdown || el.textContent;
}

function getFilename() {
    return (document.getElementById('taskInput').value.trim() || '结果')
        .slice(0, 30).replace(/[\\/:*?"<>|]/g, '_') || 'result';
}

function downloadAsMarkdown() {
    const raw = getRawMarkdown();
    const task = document.getElementById('taskInput').value.trim() || '结果';
    const md = `# ${task}\n\n${raw}\n\n---\n*由 Multi-Agent Workbench 生成*`;
    const blob = new Blob([md], { type: 'text/markdown' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = getFilename() + '.md';
    a.click();
    URL.revokeObjectURL(a.href);
}

function downloadAsText() {
    const text = document.getElementById('resultContent').textContent;
    const task = document.getElementById('taskInput').value.trim() || '结果';
    const header = `# ${task}\n\n---\n\n`;
    const blob = new Blob([header + text], { type: 'text/plain' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = getFilename() + '.txt';
    a.click();
    URL.revokeObjectURL(a.href);
}

function downloadAsHTML() {
    const raw = getRawMarkdown();
    const task = document.getElementById('taskInput').value.trim() || '结果';
    const html = marked.parse(raw);
    const fullHtml = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${escHtml(task)}</title>`
        + `<style>body{max-width:800px;margin:2rem auto;line-height:1.7;padding:0 1rem;}code{background:#f4f4f4;padding:0.2em 0.4em;border-radius:3px;}pre{background:#f4f4f4;padding:1em;border-radius:8px;overflow-x:auto;}</style>`
        + `</head><body><h1>${escHtml(task)}</h1><hr>${html}<hr><p><em>由 Multi-Agent Workbench 生成</em></p></body></html>`;
    const blob = new Blob([fullHtml], { type: 'text/html' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = getFilename() + '.html';
    a.click();
    URL.revokeObjectURL(a.href);
}

function downloadAsDocx() {
    const raw = getRawMarkdown();
    const task = document.getElementById('taskInput').value.trim() || '结果';

    // 通过后端 API 生成 DOCX
    fetch('/mawb/api/export/docx', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: raw, title: task }),
    })
    .then(resp => {
        // 检查是否返回了错误信息
        const contentType = resp.headers.get('content-type');
        if (contentType && contentType.includes('json')) {
            return resp.json().then(data => { throw new Error(data.error || data.detail || '导出失败'); });
        }
        return resp.blob();
    })
    .then(blob => {
        if (blob.size < 100) {
            // 太小的文件可能是错误信息
            blob.text().then(txt => alert('DOCX 导出失败: ' + txt));
            return;
        }
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = getFilename() + '.docx';
        a.click();
        URL.revokeObjectURL(a.href);
    })
    .catch(err => alert('DOCX 导出失败: ' + err.message));
}

function downloadAsPDF() {
    // 用浏览器打印功能导出为 PDF（支持中文、保留完整格式）
    const raw = getRawMarkdown();
    const task = document.getElementById('taskInput').value.trim() || '结果';
    const html = marked.parse(raw);

    // 创建临时页面并触发打印
    const printWin = window.open('', '_blank', 'width=800,height=600');
    if (!printWin) {
        alert('请允许弹出窗口以导出 PDF，或使用 HTML 下载后打印。');
        return;
    }
    printWin.document.write(`<!DOCTYPE html><html><head><meta charset="utf-8"><title>${escHtml(task)}</title>`
        + `<style>body{max-width:800px;margin:2rem auto;line-height:1.7;padding:0 1rem;font-family:-apple-system,Microsoft YaHei,sans-serif;}`
        + `code{background:#f4f4f4;padding:0.2em 0.4em;border-radius:3px;}pre{background:#f4f4f4;padding:1em;border-radius:8px;overflow-x:auto;}`
        + `table{border-collapse:collapse;width:100%;}th,td{border:1px solid #ddd;padding:0.5rem;}@media print{body{margin:0;padding:1cm;}}</style>`
        + `</head><body><h1>${escHtml(task)}</h1><hr>${html}<hr><p style="color:#999;font-size:0.8em;">由 Multi-Agent Workbench 生成</p>`
        + `<script>window.onload=function(){window.print();}<\/script></body></html>`);
    printWin.document.close();
}

// ===== 初始化加载设置 =====
setTimeout(loadSettings, 500);
setTimeout(setupFileUpload, 500);
setTimeout(initTaskFileUpload, 500);

// ===== 取消任务 =====
function cancelTask() {
    if (!currentTaskId) return;
    if (!confirm('确定要取消当前任务吗？')) return;
    fetch(`/mawb/api/cancel/${currentTaskId}`, { method: 'POST' })
        .then(r => r.json())
        .then(() => {
            addLog('系统', '✋ 任务已取消');
            updateStatus('error');
            document.getElementById('statusBadge').textContent = '✋ 已取消';
            stopTimer();
            enableBtn();
            document.getElementById('cancelBtn').style.display = 'none';
        });
}

// 修改runTask显示取消按钮
const origRunTask = runTask;
runTask = function() {
    origRunTask();
    document.getElementById('cancelBtn').style.display = 'inline-block';
};

// 修改enableBtn隐藏取消按钮
const origEnable = enableBtn;
enableBtn = function() {
    origEnable();
    document.getElementById('cancelBtn').style.display = 'none';
};
