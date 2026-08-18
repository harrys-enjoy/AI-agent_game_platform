/**
 * GitHub DevOps Dashboard - Single Page Interactivity Script
 */

document.addEventListener('DOMContentLoaded', () => {
  // Global Application State
  const state = {
    currentTab: 'tab-branches',
    theme: localStorage.getItem('theme') || 'dark',
    issuesData: [],
    branchesData: null,
    deploymentsData: null,
    labelChart: null
  };

  // DOM Elements
  const DOM = {
    themeToggleBtn: document.getElementById('btnThemeToggle'),
    refreshBtn: document.getElementById('btnRefresh'),
    tabButtons: document.querySelectorAll('.tab-btn'),
    tabContents: document.querySelectorAll('.tab-content'),
    
    // Status & Badges
    tokenStatusIndicator: document.getElementById('tokenStatusIndicator'),
    badgePrCount: document.getElementById('badgePrCount'),
    badgeIssueCount: document.getElementById('badgeIssueCount'),
    badgeDeployCount: document.getElementById('badgeDeployCount'),
    currentRepoBadge: document.getElementById('repoText'),

    // KPI Elements
    kpiBranchesCount: document.getElementById('kpiBranchesCount'),
    kpiOpenPrs: document.getElementById('kpiOpenPrs'),
    kpiPrMergeRate: document.getElementById('kpiPrMergeRate'),
    kpiPendingReviews: document.getElementById('kpiPendingReviews'),

    // Containers
    gitTreeContainer: document.getElementById('gitTreeContainer'),
    branchPillsColumn: document.getElementById('branchPillsColumn'),
    commitTimelineList: document.getElementById('commitTimelineList'),
    prListContainer: document.getElementById('prListContainer'),
    prListCountBadge: document.getElementById('prListCountBadge'),

    // Issue Elements
    kpiTotalIssues: document.getElementById('kpiTotalIssues'),
    kpiOpenIssues: document.getElementById('kpiOpenIssues'),
    kpiClosedIssues: document.getElementById('kpiClosedIssues'),
    kpiCriticalIssues: document.getElementById('kpiCriticalIssues'),
    colTodo: document.getElementById('colTodo'),
    colInProgress: document.getElementById('colInProgress'),
    colReview: document.getElementById('colReview'),
    colDone: document.getElementById('colDone'),
    countTodo: document.getElementById('countTodo'),
    countInProgress: document.getElementById('countInProgress'),
    countReview: document.getElementById('countReview'),
    countDone: document.getElementById('countDone'),
    aiSummaryBody: document.getElementById('aiSummaryBody'),
    aiActionsList: document.getElementById('aiActionsList'),
    issueSearchInput: document.getElementById('issueSearchInput'),
    btnChartToggle: document.getElementById('btnChartToggle'),
    labelChartWrapper: document.getElementById('labelChartWrapper'),

    // Deployment Elements
    envCardsGrid: document.getElementById('envCardsGrid'),
    deployHistoryList: document.getElementById('deployHistoryList'),

    // Modals
    modalSettings: document.getElementById('modalSettings'),
    btnOpenSettings: document.getElementById('btnOpenSettings'),
    btnCloseSettings: document.getElementById('btnCloseSettings'),
    btnCancelSettings: document.getElementById('btnCancelSettings'),
    btnSaveSettings: document.getElementById('btnSaveSettings'),
    inputOwner: document.getElementById('inputOwner'),
    inputRepo: document.getElementById('inputRepo'),
    inputToken: document.getElementById('inputToken'),

    modalLogs: document.getElementById('modalLogs'),
    btnCloseLogs: document.getElementById('btnCloseLogs'),
    terminalLogBody: document.getElementById('terminalLogBody'),
    modalLogTitle: document.getElementById('modalLogTitle')
  };

  // Initialize Application
  init();

  function init() {
    setupTheme();
    setupTabNavigation();
    setupEventListeners();
    fetchAllDashboardData();
  }

  // ==========================================
  // Theme & Navigation
  // ==========================================

  function setupTheme() {
    document.documentElement.setAttribute('data-theme', state.theme);
    updateThemeIcon();
  }

  function updateThemeIcon() {
    const icon = DOM.themeToggleBtn.querySelector('i');
    if (state.theme === 'dark') {
      icon.className = 'fa-solid fa-sun';
      DOM.themeToggleBtn.title = 'Switch to Light Mode';
    } else {
      icon.className = 'fa-solid fa-moon';
      DOM.themeToggleBtn.title = 'Switch to Dark Mode';
    }
  }

  function setupTabNavigation() {
    DOM.tabButtons.forEach(btn => {
      btn.addEventListener('click', () => {
        const targetTab = btn.getAttribute('data-tab');
        
        DOM.tabButtons.forEach(b => b.classList.remove('active'));
        DOM.tabContents.forEach(c => c.classList.remove('active'));

        btn.classList.add('active');
        document.getElementById(targetTab).classList.add('active');
        state.currentTab = targetTab;
      });
    });
  }

  function setupEventListeners() {
    // Theme Toggle
    DOM.themeToggleBtn.addEventListener('click', () => {
      state.theme = state.theme === 'dark' ? 'light' : 'dark';
      localStorage.setItem('theme', state.theme);
      setupTheme();
    });

    // Refresh Button
    DOM.refreshBtn.addEventListener('click', () => {
      DOM.refreshBtn.querySelector('i').classList.add('fa-spin');
      fetchAllDashboardData().then(() => {
        setTimeout(() => {
          DOM.refreshBtn.querySelector('i').classList.remove('fa-spin');
        }, 500);
      });
    });

    // Settings Modal
    DOM.btnOpenSettings.addEventListener('click', () => DOM.modalSettings.classList.add('active'));
    DOM.btnCloseSettings.addEventListener('click', () => DOM.modalSettings.classList.remove('active'));
    DOM.btnCancelSettings.addEventListener('click', () => DOM.modalSettings.classList.remove('active'));

    DOM.btnSaveSettings.addEventListener('click', async () => {
      const owner = DOM.inputOwner.value.trim();
      const repo = DOM.inputRepo.value.trim();
      const token = DOM.inputToken.value.trim();

      try {
        const res = await fetch('/api/config/update', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ owner, repo, token })
        });
        const result = await res.json();
        
        if (result.status === 'success') {
          DOM.currentRepoBadge.textContent = `${result.owner}/${result.repo}`;
          DOM.modalSettings.classList.remove('active');
          fetchAllDashboardData();
        }
      } catch (err) {
        alert('설정 저장 중 오류가 발생했습니다: ' + err.message);
      }
    });

    // Terminal Logs Modal Close
    DOM.btnCloseLogs.addEventListener('click', () => DOM.modalLogs.classList.remove('active'));

    // Search Input Filter
    DOM.issueSearchInput.addEventListener('input', (e) => {
      filterAndRenderIssues(e.target.value.toLowerCase());
    });

    // Label Chart Toggle
    DOM.btnChartToggle.addEventListener('click', () => {
      DOM.labelChartWrapper.classList.toggle('hidden');
    });
  }

  // ==========================================
  // Data Fetching & Rendering Orchestration
  // ==========================================

  async function fetchAllDashboardData() {
    await Promise.all([
      fetchStatus(),
      fetchBranchesAndPrs(),
      fetchIssues(),
      fetchDeployments()
    ]);
  }

  async function fetchStatus() {
    try {
      const res = await fetch('/api/status');
      const data = await res.json();
      
      if (DOM.currentRepoBadge) DOM.currentRepoBadge.textContent = `${data.owner}/${data.repo}`;
      
      if (data.has_token) {
        DOM.tokenStatusIndicator.innerHTML = `
          <span class="status-dot active"></span>
          <span>.env 토큰 연동 중</span>
        `;
      } else {
        DOM.tokenStatusIndicator.innerHTML = `
          <span class="status-dot fallback"></span>
          <span>Mock 데이터 모드</span>
        `;
      }
    } catch (e) {
      console.warn('Status fetch error', e);
    }
  }

  // 1. Fetch Branches & PRs
  async function fetchBranchesAndPrs() {
    try {
      const res = await fetch('/api/branches-prs');
      const data = await res.json();
      state.branchesData = data;

      // Update Badges & KPIs
      if (DOM.badgePrCount) DOM.badgePrCount.textContent = data.pr_summary?.total || 0;
      if (DOM.kpiBranchesCount) DOM.kpiBranchesCount.textContent = data.total_branches || 0;
      if (DOM.kpiOpenPrs) DOM.kpiOpenPrs.textContent = data.pr_summary?.open || 0;
      
      const totalPrs = data.pr_summary?.total || 1;
      const mergeRate = Math.round(((data.pr_summary?.merged || 0) / totalPrs) * 100);
      if (DOM.kpiPrMergeRate) DOM.kpiPrMergeRate.textContent = `${mergeRate}%`;

      const pendingReviews = (data.pull_requests || []).filter(pr => pr.reviewers && pr.reviewers.length > 0).length;
      if (DOM.kpiPendingReviews) DOM.kpiPendingReviews.textContent = pendingReviews;

      // Render Git Tree Graph & PR Cards
      renderGitTreeGraph(data.git_tree || [], data.branch_forks || []);
      renderPullRequestsList(data.pull_requests || []);
      renderBranchStackList(data.branches || [], data.pull_requests || []);
    } catch (err) {
      console.error('Error fetching Branches/PRs:', err);
    }
  }

  // 2. Fetch Issues
  async function fetchIssues() {
    try {
      const res = await fetch('/api/issues');
      const data = await res.json();
      state.issuesData = data.issues || [];

      // Badges & KPIs
      DOM.badgeIssueCount.textContent = data.open_count || 0;
      DOM.kpiTotalIssues.textContent = data.total_issues || 0;
      DOM.kpiOpenIssues.textContent = data.open_count || 0;
      DOM.kpiClosedIssues.textContent = data.closed_count || 0;

      const criticals = (data.issues || []).filter(i => 
        i.labels && i.labels.some(l => l.name.toLowerCase().includes('critical') || l.name.toLowerCase().includes('p0') || l.name.toLowerCase().includes('bug'))
      ).length;
      DOM.kpiCriticalIssues.textContent = criticals;

      // Render AI Summary Overview
      if (data.ai_summary) {
        DOM.aiSummaryBody.innerHTML = `<strong>최우선 조치 과제:</strong> ${data.ai_summary.top_priority}`;
        DOM.aiActionsList.innerHTML = (data.ai_summary.recommended_actions || []).map(act => `
          <li><i class="fa-solid fa-angle-right"></i> ${act}</li>
        `).join('');
      }

      // Render Kanban Board & Chart
      filterAndRenderIssues('');
      renderLabelChart(data.label_statistics || {});
    } catch (err) {
      console.error('Error fetching Issues:', err);
    }
  }

  // 3. Fetch Deployments — real kosa-deploy-* containers on this machine's Docker
  async function fetchDeployments() {
    try {
      const res = await fetch('/api/deployments');
      const data = await res.json();
      state.deploymentsData = data;

      const containers = data.containers || [];
      DOM.badgeDeployCount.textContent = containers.length;

      renderContainerCards(containers, data.docker_available);
      renderContainerList(containers, data.docker_available, data.error_msg);
    } catch (err) {
      console.error('Error fetching Deployments:', err);
    }
  }

  // ==========================================
  // Renderers: Branches & PR Visualizer
  // ==========================================

  function openCommitModal(sha, msg, author, branch) {
    const modal = document.getElementById('modalCommit');
    if (!modal) return;

    document.getElementById('modalCommitSha').textContent = sha;
    document.getElementById('modalCommitMsg').textContent = msg || 'Commit 상세 정보';
    document.getElementById('modalCommitAuthor').textContent = author || 'dev-lead';
    document.getElementById('modalCommitBranch').textContent = branch || 'main';

    const githubOwner = document.getElementById('inputOwner')?.value || 'octocat';
    const githubRepo = document.getElementById('inputRepo')?.value || 'Hello-World';
    const githubUrl = `https://github.com/${githubOwner}/${githubRepo}/commit/${sha}`;

    const githubLinkEl = document.getElementById('modalCommitGithubUrl');
    if (githubLinkEl) {
      githubLinkEl.href = githubUrl;
    }

    modal.classList.add('active');
  }

  window.openCommitModal = openCommitModal;

  const LANE_COLORS = ['#a855f7', '#ea580c', '#eab308', '#06b6d4', '#10b981', '#f43f5e', '#6366f1', '#38bdf8'];

  function renderGitTreeGraph(treeNodes, branchForks) {
    if (DOM.branchPillsColumn) DOM.branchPillsColumn.innerHTML = '';

    if (!treeNodes.length) {
      DOM.gitTreeContainer.innerHTML = `<div class="text-center" style="padding: 2rem; color: var(--text-dim);">표시할 커밋이 없습니다.</div>`;
      DOM.commitTimelineList.innerHTML = '';
      return;
    }

    // Oldest commit on the left, newest on the right
    const nodes = [...treeNodes].reverse();

    // One lane per unique branch, in order of first appearance
    // ponytail: lane = raw branch string, no parent/child merge-edge math — real git_tree data has no reliable parent graph across mixed live/mock sources
    const laneIndex = new Map();
    nodes.forEach(n => {
      if (!laneIndex.has(n.branch)) laneIndex.set(n.branch, laneIndex.size);
    });
    const lanes = [...laneIndex.keys()];
    const colorOf = (branch) => LANE_COLORS[laneIndex.get(branch) % LANE_COLORS.length];

    const padX = 40;
    const width = 900;
    const rowHeight = 40;
    const topPad = 30;
    const height = topPad * 2 + (lanes.length - 1) * rowHeight;
    const xStep = nodes.length > 1 ? (width - padX * 2) / (nodes.length - 1) : 0;
    const xOf = (idx) => padX + idx * xStep;
    const yOf = (branch) => topPad + laneIndex.get(branch) * rowHeight;

    const laneLines = lanes.map(branch => {
      const xs = nodes.map((n, idx) => n.branch === branch ? xOf(idx) : null).filter(x => x !== null);
      const x1 = Math.min(...xs);
      const x2 = Math.max(Math.max(...xs), x1 + 1);
      const y = yOf(branch);
      return `<line x1="${x1}" y1="${y}" x2="${x2}" y2="${y}" stroke="${colorOf(branch)}" stroke-width="4" stroke-linecap="round" />`;
    }).join('');

    // Connector lines from each branch's real merge-base commit (backend-resolved via
    // GitHub's /compare) to that branch's own oldest commit — shows where it actually
    // forked instead of leaving lanes floating unconnected.
    const forkConnectors = (branchForks || []).map(fork => {
      const forkIdx = nodes.findIndex(n => n.sha === fork.fork_sha);
      const childIndices = nodes.map((n, idx) => n.branch === fork.branch ? idx : null).filter(idx => idx !== null);
      if (forkIdx === -1 || childIndices.length === 0 || !laneIndex.has(fork.branch)) return '';
      const childIdx = Math.min(...childIndices);
      const x1 = xOf(forkIdx), y1 = yOf(nodes[forkIdx].branch);
      const x2 = xOf(childIdx), y2 = yOf(fork.branch);
      return `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${colorOf(fork.branch)}" stroke-width="2" stroke-dasharray="5,4" opacity="0.7" />`;
    }).join('');

    const nodeMarkers = nodes.map((n, idx) => {
      const x = xOf(idx);
      const y = yOf(n.branch);
      const color = colorOf(n.branch);
      const safeMsg = (n.message || '').replace(/'/g, "\\'").replace(/"/g, '&quot;');
      return `
        <g style="cursor: pointer;" onclick="openCommitModal('${n.sha}', '${safeMsg}', '${n.author}', '${n.branch}')">
          <title>${n.sha} · ${(n.message || '').replace(/</g, '&lt;')}</title>
          <circle cx="${x}" cy="${y}" r="13" fill="#0f172a" stroke="${color}" stroke-width="4"/>
          <circle cx="${x}" cy="${y}" r="5" fill="${color}"/>
          <text x="${x}" y="${y - 18}" fill="#f3f4f6" font-size="11" font-weight="700" text-anchor="middle" font-family="Fira Code">${n.sha}</text>
        </g>
      `;
    }).join('');

    DOM.gitTreeContainer.innerHTML = `
      <svg width="100%" height="${height}" viewBox="0 0 ${width} ${height}" xmlns="http://www.w3.org/2000/svg">
        ${laneLines}
        ${forkConnectors}
        ${nodeMarkers}
      </svg>
    `;

    if (DOM.branchPillsColumn) {
      DOM.branchPillsColumn.innerHTML = lanes.map(branch => `
        <div class="branch-pill" style="background: ${colorOf(branch)};" title="${branch}">
          <i class="fa-solid fa-code-branch"></i> ${branch.toUpperCase()}
        </div>
      `).join('');
    }

    // Render Timeline Items (Linear Row Matrix with Click Handlers)
    DOM.commitTimelineList.innerHTML = treeNodes.map(node => `
      <div class="commit-node-item ${node.branch.includes('feature') || node.branch.includes('hotfix') ? 'feature' : 'main'}" style="cursor: pointer;" onclick="openCommitModal('${node.sha}', '${node.message.replace(/'/g, "\\'")}', '${node.author}', '${node.branch}')">
        <div class="commit-meta">
          <span class="commit-sha">${node.sha}</span>
          <div>
            <div class="commit-msg">${node.message}</div>
            <div class="commit-author-time">작성자: <strong>${node.author}</strong> • ${node.date}</div>
          </div>
        </div>
        <span class="pr-branch-flow"><span>${node.branch}</span></span>
      </div>
    `).join('');
  }

  function renderPullRequestsList(prs) {
    if (DOM.prListCountBadge) DOM.prListCountBadge.textContent = `${prs.length} PRs`;
    if (!DOM.prListContainer) return;
    
    if (prs.length === 0) {
      DOM.prListContainer.innerHTML = `<div class="text-center" style="padding: 2rem; color: var(--text-dim);">등록된 Pull Request가 없습니다.</div>`;
      return;
    }

    DOM.prListContainer.innerHTML = prs.map(pr => {
      let stateBadge = `<span class="badge badge-open"><i class="fa-regular fa-circle-dot"></i> Open</span>`;
      if (pr.state === 'merged') {
        stateBadge = `<span class="badge badge-merged"><i class="fa-solid fa-code-merge"></i> Merged</span>`;
      } else if (pr.state === 'closed') {
        stateBadge = `<span class="badge badge-closed"><i class="fa-solid fa-circle-xmark"></i> Closed</span>`;
      }

      return `
        <div class="pr-card">
          <div class="pr-card-header">
            <div class="pr-title-group">
              <a href="${pr.html_url || '#'}" target="_blank" class="pr-title">
                <span class="pr-number">#${pr.number}</span> ${pr.title}
              </a>
              <div class="pr-branch-flow">
                <span>${pr.head}</span> <i class="fa-solid fa-arrow-right"></i> <span>${pr.base}</span>
              </div>
            </div>
            ${stateBadge}
          </div>

          <div style="display: flex; align-items: center; justify-content: space-between;">
            <div style="display: flex; align-items: center; gap: 0.5rem;">
              <img src="${pr.author.avatar_url}" class="assignee-avatar" title="${pr.author.login}">
              <span style="font-size: 0.78rem; color: var(--text-muted);">${pr.author.login}</span>
            </div>

            <div class="diff-stat">
              <span class="diff-add">+${pr.additions || 0}</span>
              <span class="diff-del">-${pr.deletions || 0}</span>
            </div>
          </div>
        </div>
      `;
    }).join('');
  }

  // ==========================================
  // Renderers: Issues Kanban Board
  // ==========================================

  function filterAndRenderIssues(query) {
    const filtered = state.issuesData.filter(i => {
      const matchTitle = i.title.toLowerCase().includes(query);
      const matchNum = i.number.toString().includes(query);
      return matchTitle || matchNum;
    });

    const todo = filtered.filter(i => i.kanban_status === 'todo');
    const inProgress = filtered.filter(i => i.kanban_status === 'in_progress');
    const review = filtered.filter(i => i.kanban_status === 'review');
    const done = filtered.filter(i => i.kanban_status === 'done');

    DOM.countTodo.textContent = todo.length;
    DOM.countInProgress.textContent = inProgress.length;
    DOM.countReview.textContent = review.length;
    DOM.countDone.textContent = done.length;

    DOM.colTodo.innerHTML = renderIssueCardsGroup(todo);
    DOM.colInProgress.innerHTML = renderIssueCardsGroup(inProgress);
    DOM.colReview.innerHTML = renderIssueCardsGroup(review);
    DOM.colDone.innerHTML = renderIssueCardsGroup(done);
  }

  function renderIssueCardsGroup(issues) {
    if (issues.length === 0) {
      return `<div style="text-align: center; padding: 1.5rem; color: var(--text-dim); font-size: 0.8rem;">이슈 없음</div>`;
    }

    return issues.map(i => {
      const labelsHtml = (i.labels || []).map(l => 
        `<span class="label-chip" style="background-color: #${l.color || '3b82f6'};">${l.name}</span>`
      ).join('');

      const avatar = i.assignees && i.assignees.length > 0 
        ? `<img src="${i.assignees[0].avatar_url}" class="assignee-avatar" title="${i.assignees[0].login}">`
        : `<i class="fa-regular fa-user" style="color: var(--text-dim);"></i>`;

      return `
        <div class="issue-kanban-card">
          <div style="font-size: 0.75rem; color: var(--text-muted); font-family: 'Fira Code', monospace;">#${i.number}</div>
          <div class="issue-title">${i.title}</div>
          <div class="label-chips">${labelsHtml}</div>
          <div class="issue-card-footer">
            <span><i class="fa-regular fa-comment"></i> ${i.comments_count || 0}</span>
            ${avatar}
          </div>
        </div>
      `;
    }).join('');
  }

  function renderLabelChart(labelStats) {
    const ctx = document.getElementById('labelDistributionChart');
    if (!ctx) return;

    const labels = Object.keys(labelStats);
    const data = Object.values(labelStats);

    if (state.labelChart) {
      state.labelChart.destroy();
    }

    state.labelChart = new Chart(ctx, {
      type: 'doughnut',
      data: {
        labels: labels,
        datasets: [{
          data: data,
          backgroundColor: ['#38bdf8', '#a855f7', '#10b981', '#f59e0b', '#f43f5e', '#6366f1'],
          borderWidth: 0
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            position: 'bottom',
            labels: { color: state.theme === 'dark' ? '#f3f4f6' : '#0f172a' }
          }
        }
      }
    });
  }

  // ==========================================
  // Renderers: Local Docker Deployment Containers
  // ==========================================

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  function renderContainerCards(containers, dockerAvailable) {
    if (!DOM.envCardsGrid) return;

    if (dockerAvailable === false) {
      DOM.envCardsGrid.innerHTML = `<div class="text-center" style="padding: 2rem; color: var(--text-dim);">이 서버/PC에서 Docker를 사용할 수 없습니다.</div>`;
      return;
    }
    if (containers.length === 0) {
      DOM.envCardsGrid.innerHTML = `<div class="text-center" style="padding: 2rem; color: var(--text-dim);">kosa-deploy-* 컨테이너가 없습니다. deploy_trigger로 배포하면 여기에 표시됩니다.</div>`;
      return;
    }

    DOM.envCardsGrid.innerHTML = containers.map(c => `
      <div class="glass-panel env-card">
        <div class="env-card-header">
          <span class="env-name" style="display: flex; align-items: center; gap: 0.5rem; font-weight: 800;">
            <i class="fa-solid fa-box" style="color: var(--primary);"></i>
            <span>${escapeHtml(c.repo)}</span>
          </span>
          <span class="badge ${c.running ? 'badge-open' : 'badge-closed'}">${c.running ? 'RUNNING' : 'STOPPED'}</span>
        </div>

        <div style="font-family: 'Fira Code', monospace; font-size: 0.82rem; margin-top: 0.4rem;">
          <div>포트: <strong>${escapeHtml(c.ports || '-')}</strong></div>
          <div style="color: var(--text-dim);">${escapeHtml(c.status)}</div>
        </div>

        <div class="metric-bar-group">
          <div class="metric-label"><span>CPU 사용률</span><span>${escapeHtml(c.cpu_usage || '-')}</span></div>
          <div class="progress-track"><div class="progress-fill" style="width: ${parseFloat(c.cpu_usage) || 0}%;"></div></div>
        </div>

        <div class="metric-bar-group">
          <div class="metric-label"><span>Memory 사용량</span><span>${escapeHtml(c.memory_usage || '-')}</span></div>
        </div>
      </div>
    `).join('');
  }

  function renderContainerList(containers, dockerAvailable, errorMsg) {
    if (dockerAvailable === false) {
      DOM.deployHistoryList.innerHTML = `<div class="text-center" style="padding: 2rem; color: var(--text-dim);">Docker 조회 실패${errorMsg ? `: ${escapeHtml(errorMsg)}` : ''}</div>`;
      return;
    }
    if (containers.length === 0) {
      DOM.deployHistoryList.innerHTML = `<div class="text-center" style="padding: 2rem;">표시할 컨테이너가 없습니다.</div>`;
      return;
    }

    DOM.deployHistoryList.innerHTML = containers.map(c => `
      <div class="pr-card">
        <div class="pr-card-header">
          <div class="pr-title-group">
            <div class="pr-title">
              <i class="fa-solid fa-box"></i> ${escapeHtml(c.name)}
            </div>
            <div style="font-size: 0.78rem; color: var(--text-dim);">${escapeHtml(c.image)}</div>
          </div>
          <span class="badge ${c.running ? 'badge-open' : 'badge-closed'}">${escapeHtml(c.status)}</span>
        </div>
        <div style="display: flex; align-items: center; justify-content: space-between; margin-top: 0.5rem;">
          <div style="font-size: 0.75rem; color: var(--text-muted); font-family: 'Fira Code', monospace;">
            ${escapeHtml(c.ports || '포트 없음')} • ${escapeHtml(c.created_at)}
          </div>
          <button class="btn btn-secondary btn-view-log" data-container-name="${escapeHtml(c.name)}">
            <i class="fa-solid fa-terminal"></i> 로그 보기
          </button>
        </div>
      </div>
    `).join('');

    document.querySelectorAll('.btn-view-log').forEach(btn => {
      btn.addEventListener('click', () => {
        openTerminalLogModal(btn.getAttribute('data-container-name'));
      });
    });
  }

  async function openTerminalLogModal(containerName) {
    DOM.modalLogTitle.textContent = `${containerName} — 컨테이너 로그`;
    DOM.terminalLogBody.innerHTML = `<div class="log-line info">로그를 불러오는 중...</div>`;
    DOM.modalLogs.classList.add('active');

    try {
      const res = await fetch(`/api/deployments/${encodeURIComponent(containerName)}/logs`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        DOM.terminalLogBody.innerHTML = `<div class="log-line error">로그를 불러오지 못했습니다: ${escapeHtml(err.detail || res.statusText)}</div>`;
        return;
      }
      const data = await res.json();
      const lines = (data.logs || '(로그 없음)').split('\n');
      DOM.terminalLogBody.innerHTML = lines.map(line => `<div class="log-line info">${escapeHtml(line)}</div>`).join('');
    } catch (err) {
      DOM.terminalLogBody.innerHTML = `<div class="log-line error">로그를 불러오지 못했습니다: ${escapeHtml(err.message)}</div>`;
    }
  }

  // ==========================================
  // Renderers: Vertical Stacked Branch Cards
  // ==========================================

  function renderBranchStackList(branches, prs) {
    const container = document.getElementById('branchStackContainer');
    const badge = document.getElementById('branchStackCountBadge');
    if (!container) return;

    badge.textContent = `${branches.length} Branches`;

    if (branches.length === 0) {
      container.innerHTML = `<div class="text-center" style="padding: 2rem; color: var(--text-dim);">등록된 브랜치가 없습니다.</div>`;
      return;
    }

    container.innerHTML = branches.map((b, idx) => {
      const bName = b.name;
      const isLast = idx === branches.length - 1;
      const treePrefix = isLast ? '└──' : '├──';

      let cardType = 'feature';
      if (bName === 'main' || bName === 'master') cardType = 'main';
      else if (bName === 'develop' || bName === 'dev') cardType = 'develop';
      else if (bName.startsWith('fix/') || bName.startsWith('hotfix/')) cardType = 'hotfix';

      const linkedPr = prs.find(pr => pr.head === bName);

      let prBoxHtml = '';
      if (linkedPr) {
        let stateBadgeClass = 'badge-open';
        if (linkedPr.state === 'merged') stateBadgeClass = 'badge-merged';
        if (linkedPr.state === 'closed') stateBadgeClass = 'badge-closed';

        prBoxHtml = `
          <div class="branch-pr-linked-box">
            <div style="font-size: 0.8rem; font-weight: 700; color: var(--primary); display: flex; align-items: center; justify-content: space-between;">
              <span><i class="fa-solid fa-code-pull-request"></i> 연결된 PR #${linkedPr.number} (${linkedPr.head} ➔ ${linkedPr.base})</span>
              <span class="badge ${stateBadgeClass}">${linkedPr.draft ? 'DRAFT' : linkedPr.state.toUpperCase()}</span>
            </div>
            <div style="font-size: 0.88rem; font-weight: 600; color: var(--text-main); margin-top: 0.2rem;">${linkedPr.title}</div>
            <div style="font-size: 0.78rem; color: var(--text-muted); display: flex; gap: 1.25rem; align-items: center; margin-top: 0.4rem;">
              <span><i class="fa-regular fa-user"></i> 작성자: <strong>${linkedPr.author.login}</strong></span>
              <span><i class="fa-solid fa-user-check"></i> 리뷰: <strong>${linkedPr.review_status || 'PENDING'}</strong></span>
              <span class="diff-stat"><span class="diff-add">+${linkedPr.additions || 0}</span> <span class="diff-del">-${linkedPr.deletions || 0}</span></span>
            </div>
          </div>
        `;
      } else {
        prBoxHtml = `
          <div class="branch-commit-box">
            <div style="font-size: 0.78rem; font-weight: 600; color: var(--text-dim);">연결된 PR 상태</div>
            <div style="font-size: 0.82rem; color: var(--text-muted);">오픈된 Pull Request 없음 (독립 개발 브랜치)</div>
          </div>
        `;
      }

      return `
        <div class="branch-stack-card ${cardType}">
          <div class="branch-stack-header">
            <div class="branch-stack-title-group">
              <span class="branch-index-badge">${treePrefix} 브랜치 #${idx + 1}</span>
              <span class="branch-stack-name"><i class="fa-solid fa-folder-tree"></i> ${bName}</span>
            </div>
            <div style="display: flex; align-items: center; gap: 0.5rem;">
              ${b.protected ? '<span class="badge badge-open"><i class="fa-solid fa-lock"></i> Protected</span>' : '<span class="badge badge-merged">Active</span>'}
              <span class="commit-sha">sha: ${b.commit_sha}</span>
            </div>
          </div>

          <div class="branch-stack-info">
            <div class="branch-commit-box">
              <div class="branch-commit-title"><i class="fa-solid fa-code-commit"></i> 최근 커밋: ${b.commit_msg || b.commit_sha}</div>
              <div class="branch-commit-meta">디렉토리 경로: <code>refs/heads/${bName}</code> • 커밋 <code>${b.commit_sha}</code></div>
            </div>
            ${prBoxHtml}
          </div>

          <div class="branch-stack-actions">
            <div style="font-size: 0.78rem; color: var(--text-dim); font-family: 'Fira Code', monospace;">
              <span>Target: <strong>${bName === 'main' ? 'production-base' : 'develop'}</strong></span>
            </div>
            <div style="display: flex; gap: 0.5rem;">
              <a href="${b.commit_url || '#'}" target="_blank" class="btn btn-secondary" style="font-size: 0.78rem; padding: 0.35rem 0.75rem;">
                <i class="fa-brands fa-github"></i> GitHub에서 보기
              </a>
            </div>
          </div>
        </div>
      `;
    }).join('');
  }

  // Close Commit Modal listener
  const btnCloseCommit = document.getElementById('btnCloseCommitModal');
  if (btnCloseCommit) {
    btnCloseCommit.addEventListener('click', () => {
      document.getElementById('modalCommit')?.classList.remove('active');
    });
  }

  // Copy SHA listener
  const btnCopySha = document.getElementById('btnCopySha');
  if (btnCopySha) {
    btnCopySha.addEventListener('click', () => {
      const sha = document.getElementById('modalCommitSha')?.textContent;
      if (sha) {
        navigator.clipboard.writeText(sha);
        showToast(`Commit SHA 복사 완료: ${sha}`);
      }
    });
  }

});
