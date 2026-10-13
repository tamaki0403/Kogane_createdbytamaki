(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[char]);
  const number = (value) => Number.isFinite(Number(value)) ? Number(value) : 0;
  const statusText = {
    setup: "準備中", registration: "参加受付中", running: "進行中",
    qualifier: "予選進行中", bracket: "本戦進行中", done: "終了",
    active: "進行中", waiting: "開始前", hold: "保留", disputed: "確認中"
  };

  let snapshot = null;
  let currentLeague = "upper";
  let selectedGroup = null;
  let eventSource = null;
  let fallbackTimer = null;
  let loading = false;

  function team(teamId) {
    return snapshot?.teams?.[teamId] || {
      team_id: teamId, name: teamId ? "未登録チーム" : "未確定",
      placement_number: "", application_number: null, members: []
    };
  }

  function teamName(teamId) {
    return teamId ? team(teamId).name : "未確定";
  }

  function teamLink(teamId, fallback = "未確定") {
    if (!teamId) return `<span class="bracket-name pending">${esc(fallback)}</span>`;
    const item = team(teamId);
    return `<span class="bracket-name" role="button" tabindex="0" data-team-id="${esc(teamId)}">${esc(item.name)}</span>`;
  }

  function allGroups() {
    return (snapshot?.qualifier_blocks || []).flatMap((block) => block.groups || []);
  }

  function adaptGroup(group) {
    const matches = group.matches || [];
    const confirmed = Boolean(group.advancement_confirmed);
    return {
      id: group.group_id,
      block: group.section,
      range: group.start_position && group.end_position
        ? `${group.start_position}〜${group.end_position}` : "",
      complete: number(group.complete_matches),
      total: number(group.total_matches),
      confirmed,
      teams: (group.teams || []).map((entry) => {
        const data = team(entry.team_id);
        const record = entry.record || {};
        return {
          id: entry.team_id,
          position: entry.position || data.placement_number || "",
          name: data.name,
          application: data.application_number,
          rank: entry.rank,
          confirmed,
          wins: number(record.match_wins),
          losses: number(record.match_losses),
          battleWins: number(record.battle_wins),
          battleLosses: number(record.battle_losses),
          qualified: Boolean(entry.advancement_confirmed && entry.advancement === "upper"),
          provisional: Boolean(!entry.advancement_confirmed && entry.provisional_advancement === "upper")
        };
      }),
      matches
    };
  }

  function teamRow(item, detail = false) {
    const classes = ["team-row"];
    if (item.qualified) classes.push("qualified");
    const record = detail
      ? (item.confirmed ? String(item.wins) : "—")
      : `${item.wins}-${item.losses}`;
    const rank = detail && item.confirmed && item.rank ? ` · ${item.rank}位` : "";
    const provisional = item.provisional ? "（暫定上位）" : "";
    return `<div class="${classes.join(" ")}" title="${esc(provisional)}">
      <span class="seed">${esc(item.position)}</span>
      <span class="team-name" role="button" tabindex="0" data-team-id="${esc(item.id)}">${esc(item.name)}${esc(rank)}</span>
      <span class="record">${esc(record)}</span>
    </div>`;
  }

  function groupCard(group, staticCard = false) {
    const done = group.confirmed ? "進出確定" : `${group.complete}/${group.total}試合`;
    const tag = staticCard ? "div" : "button";
    const attrs = staticCard ? "" : ` type="button" data-group-id="${esc(group.id)}"`;
    return `<${tag} class="group-card"${attrs}>
      <div class="group-head"><strong>${esc(group.range)}</strong><span class="done">${esc(done)}</span></div>
      <div class="team-list">${group.teams.map((item) => teamRow(item, staticCard)).join("")}</div>
      <div class="group-foot"><span>${esc(group.range)} / ${group.teams.length}チーム</span>${staticCard ? "" : '<span class="arrow">→</span>'}</div>
    </${tag}>`;
  }

  function renderQualifiers() {
    const blocks = snapshot.qualifier_blocks || [];
    $("#qual .sub").innerHTML = `${number(snapshot.team_count)}チーム / ${number(snapshot.group_count)}組　<span aria-hidden="true">·</span>　カードを押すと対戦結果を表示`;
    $("#qual-groups").innerHTML = blocks.length ? blocks.map((block) => {
      const groups = (block.groups || []).map(adaptGroup);
      return `<section class="qual-block">
        <div class="block-heading"><h3>${esc(block.block_id)}</h3><span>BLOCK</span><small>${number(block.team_count)} teams</small></div>
        <div class="group-list">${groups.map((group) => groupCard(group)).join("")}</div>
      </section>`;
    }).join("") : '<p class="sub">予選データはまだありません。</p>';
  }

  function scheduledRounds(group) {
    const rounds = [[], [], []];
    for (const match of group.matches) {
      let placed = false;
      for (const round of rounds) {
        const occupied = new Set(round.flatMap((item) => item.team_ids || []));
        if ((match.team_ids || []).every((id) => !occupied.has(id))) {
          round.push(match);
          placed = true;
          break;
        }
      }
      if (!placed) rounds[rounds.length - 1].push(match);
    }
    return rounds;
  }

  function resultCard(match) {
    const ids = match.team_ids || [];
    const score = match.score;
    const winner = match.winner_team_id;
    const state = match.status === "done" ? "確定" :
      match.report_state === "mismatch" ? "報告不一致" :
      match.report_state === "one_sided" ? "片側報告" :
      statusText[match.status] || "未確定";
    const rows = ids.map((id, index) => {
      const data = team(id);
      const won = winner === id;
      return `<div class="team-row ${won ? "winner" : ""}">
        <span class="seed">${esc(data.placement_number || "")}</span>
        <span class="team-name" role="button" tabindex="0" data-team-id="${esc(id)}">${esc(data.name)}</span>
        <span class="record">${score ? number(score[index]) : "—"}</span>
      </div>`;
    }).join("");
    return `<article class="result-card">
      <div class="match-meta"><span>${esc(match.match_id || "対戦")}</span><span>${esc(state)}</span></div>
      ${rows || '<p class="sub">対戦チーム未確定</p>'}
    </article>`;
  }

  function openGroup(groupId) {
    const raw = allGroups().find((item) => item.group_id === groupId);
    if (!raw) return;
    const group = adaptGroup(raw);
    selectedGroup = groupId;
    $("#qual").hidden = true;
    $("#bracket").hidden = true;
    $("#detail").hidden = false;
    $("#detail-title").textContent = `${group.range} 詳細`;
    const complete = group.matches.filter((match) => match.status === "done").length;
    $("#detail .status").textContent = `${complete}/${group.matches.length}試合 確定`;
    const rounds = scheduledRounds(group);
    $("#detail-content").innerHTML = `
      <div class="detail-col"><div class="label">参加チーム</div>${groupCard(group, true)}
        <p class="detail-note">申請番号はチーム名を押すと確認できます。勝利数と順位は予選組の全対戦が確定した後に表示します。</p></div>
      ${rounds.map((items, index) => `<div class="detail-col"><div class="label">第${index + 1}試合</div>${items.length ? items.map(resultCard).join("") : '<p class="sub">対戦データはありません。</p>'}</div>`).join("")}`;
    $("#detail-title").focus();
  }

  function roundMatch(bracket, round, index, expectedIds = []) {
    const matches = (bracket?.matches || [])
      .filter((match) => number(match.round) === round)
      .sort((a, b) => String(a.match_id).localeCompare(String(b.match_id), "ja"));
    if (expectedIds.length === 2) {
      const expected = [...expectedIds].sort().join("\u0000");
      const exact = matches.find((match) => [...(match.team_ids || [])].sort().join("\u0000") === expected);
      if (exact) return exact;
    }
    return matches[index] || null;
  }

  function matchRows(match, fallbackSlots) {
    const ids = match?.team_ids?.length === 2 ? match.team_ids : fallbackSlots.map((slot) => slot.teamId || null);
    const score = match?.score;
    return ids.map((id, index) => {
      const fallback = fallbackSlots[index]?.label || "未確定";
      const data = id ? team(id) : null;
      return `<div class="bracket-team ${match?.winner_team_id === id ? "winner" : ""}">
        <span class="seed">${esc(data?.placement_number || "")}</span>
        ${teamLink(id, fallback)}
        ${score ? `<span class="record">${number(score[index])}</span>` : ""}
      </div>`;
    }).join("");
  }

  function matchCard(node, final = false) {
    const match = node.match;
    const state = match?.status === "done" ? "確定" :
      match?.report_state === "mismatch" ? "確認中" :
      match?.report_state === "one_sided" ? "報告待ち" :
      statusText[match?.status] || "開始前";
    const label = match?.match_id || node.label;
    return `<article class="bracket-match${final ? " final" : ""}" style="left:${node.x}px;top:${node.y}px">
      <div class="match-meta"><span>${esc(label)}</span><span>${esc(state)}</span></div>
      ${matchRows(match, node.slots)}
    </article>`;
  }

  function bracketRoundName(round, totalRounds) {
    if (round === totalRounds) return "決勝";
    if (round === totalRounds - 1) return "準決勝";
    if (round === totalRounds - 2) return "準々決勝";
    return `${round}回戦`;
  }

  function renderBracket() {
    const bracket = snapshot[currentLeague === "upper" ? "upper_bracket" : "lower_bracket"];
    const accentName = currentLeague === "upper" ? "Aリーグ" : "Bリーグ";
    $("#bracket").dataset.league = currentLeague;
    $("#league-desc").textContent = bracket ? `${accentName} / ${number(bracket.active_team_count)}チーム` : `${accentName} / 未生成`;
    $("#bracket .status").textContent = bracket ? (statusText[snapshot.status] || "進行状況") : "未生成";
    renderSideResults(bracket);
    const hasEntrants = Boolean(bracket) && (
      (bracket.initial_slots || []).some(Boolean) ||
      (bracket.slot_sources || []).some(Boolean)
    );
    if (!hasEntrants) {
      $("#bracket-canvas").innerHTML = '<p class="sub" style="padding:30px">対戦表はまだ生成されていません。</p>';
      $(".bracket-caption").innerHTML = "<strong>本戦データ未生成</strong>";
      return;
    }

    const initial = bracket.initial_slots;
    const slotSources = bracket.slot_sources || [];
    const initialEntries = initial.map((teamId, index) => {
      if (teamId) return {teamId, label: teamName(teamId)};
      const source = slotSources[index];
      return source ? {label: source.label, source} : null;
    });
    const size = initial.length;
    const teamCount = number(bracket.active_team_count) || initialEntries.filter(Boolean).length;
    const totalRounds = Math.max(1, Math.log2(size));
    const firstRoundName = bracketRoundName(1, totalRounds);
    if (size === 2) {
      const ids = initial.filter(Boolean);
      const match = roundMatch(bracket, 1, 0, ids);
      const canvas = $("#bracket-canvas");
      canvas.style.width = "460px";
      canvas.style.height = "360px";
      canvas.innerHTML = `<div class="round-title" style="left:18px">決勝<span>1試合</span></div>${matchCard({
        x: 18, y: 80, match, label: match?.match_id || "決勝",
        slots: initialEntries.map((entry) => entry || {label: "未確定"})
      }, true)}`;
      $(".bracket-scroll").setAttribute("aria-label", `${teamCount}チームの決勝戦`);
      $(".bracket-caption").innerHTML = `<strong>${teamCount}チーム / 全${Math.max(0, teamCount - 1)}試合</strong><span>Botで確定した結果を表示します。</span>`;
      return;
    }
    const columns = [];
    const sourcePairs = [];
    for (let index = 0; index < size; index += 2) sourcePairs.push(initialEntries.slice(index, index + 2));

    const secondCount = Math.max(1, size / 4);
    const sourceBounds = Array.from({length: secondCount}, (_, index) => {
      const bounds = [];
      [0, 1].forEach((targetSlot) => {
        const pair = sourcePairs[index * 2 + targetSlot] || [];
        const entryCount = pair.filter(Boolean).length;
        if (!entryCount) return;
        const isMatch = entryCount === 2;
        const top = isMatch
          ? (targetSlot ? 64 : -64)
          : 24 + targetSlot * 30;
        bounds.push({top, bottom: top + (isMatch ? 86 : 30)});
      });
      if (!bounds.length) return {min: 24, max: 54};
      return {
        min: Math.min(...bounds.map((bound) => bound.top)),
        max: Math.max(...bounds.map((bound) => bound.bottom))
      };
    });
    const secondNodes = [];
    sourceBounds.forEach((bounds, index) => {
      const previous = sourceBounds[index - 1];
      const previousNode = secondNodes[index - 1];
      const y = index === 0
        ? Math.max(80, 64 - bounds.min)
        : previousNode.y + Math.max(146, previous.max - bounds.min + 24);
      secondNodes.push({
        round: 2, index, x: 244, y,
        label: `${bracketRoundName(2, totalRounds)} ${index + 1}`,
        slots: [{label: `${firstRoundName}の勝者`}, {label: `${firstRoundName}の勝者`}], match: null
      });
    });
    columns.push(secondNodes);

    const sources = [];
    sourcePairs.forEach((pair, pairIndex) => {
      const entries = pair.filter(Boolean);
      const actualTeamIds = entries.map((entry) => entry.teamId).filter(Boolean);
      const target = secondNodes[Math.floor(pairIndex / 2)];
      const targetSlot = pairIndex % 2;
      if (entries.length === 2) {
        const match = actualTeamIds.length === 2
          ? roundMatch(bracket, 1, pairIndex, actualTeamIds)
          : null;
        // Leave a clear gap from the adjacent one-team entry.  Both still
        // connect to their original slots on the same second-round card.
        const y = target.y + (targetSlot ? 64 : -64);
        const source = {kind: "match", x: 18, y, match, slots: entries, target, targetSlot};
        sources.push(source);
        target.slots[targetSlot] = match?.status === "done" && match.winner_team_id
          ? {teamId: match.winner_team_id, label: teamName(match.winner_team_id)}
          : {label: `${match?.match_id || firstRoundName}の勝者`};
      } else if (entries.length === 1) {
        const y = target.y + 24 + targetSlot * 30;
        sources.push({kind: "entry", x: 18, y, slot: entries[0], target, targetSlot});
        target.slots[targetSlot] = entries[0];
      }
    });

    secondNodes.forEach((node) => {
      node.match = roundMatch(bracket, 2, node.index, node.slots.map((slot) => slot.teamId).filter(Boolean));
      if (node.match?.team_ids?.length === 2) {
        node.slots = node.match.team_ids.map((id) => ({teamId: id, label: teamName(id)}));
      }
    });

    let previous = secondNodes;
    for (let round = 3; round <= totalRounds; round += 1) {
      const count = Math.max(1, size / (2 ** round));
      const nodes = Array.from({length: count}, (_, index) => {
        const inputs = previous.slice(index * 2, index * 2 + 2);
        const y = inputs.length === 2
          ? ((inputs[0].y + 43 + inputs[1].y + 43) / 2) - 43
          : inputs[0].y;
        const slots = inputs.map((input) => input.match?.status === "done" && input.match.winner_team_id
          ? {teamId: input.match.winner_team_id, label: teamName(input.match.winner_team_id)}
          : {label: `${input.match?.match_id || input.label}の勝者`});
        while (slots.length < 2) slots.push({label: "未確定"});
        const node = {
          round, index, x: 244 + (round - 2) * 226, y,
          label: round === totalRounds ? "決勝" : `${bracketRoundName(round, totalRounds)} ${index + 1}`,
          slots, match: null, inputs
        };
        node.match = roundMatch(bracket, round, index, slots.map((slot) => slot.teamId).filter(Boolean));
        if (node.match?.team_ids?.length === 2) {
          node.slots = node.match.team_ids.map((id) => ({teamId: id, label: teamName(id)}));
        }
        return node;
      });
      columns.push(nodes);
      previous = nodes;
    }

    const edges = [];
    const edge = (x1, y1, x2, y2) => {
      const middle = Math.round((x1 + x2) / 2);
      edges.push(`M ${x1} ${y1} H ${middle} V ${y2} H ${x2}`);
    };
    sources.forEach((source) => {
      const startY = source.y + (source.kind === "match" ? 43 : 15);
      const endY = source.target.y + (source.targetSlot === 0 ? 39 : 69);
      edge(source.x + 196, startY, source.target.x, endY);
    });
    columns.slice(1).forEach((nodes) => nodes.forEach((node) => {
      (node.inputs || []).forEach((input, slot) => edge(input.x + 196, input.y + 43, node.x, node.y + (slot === 0 ? 39 : 69)));
    }));

    const firstMatchCount = sources.filter((source) => source.kind === "match").length;
    const titles = [
      {x: 18, name: firstRoundName, count: `${firstMatchCount}試合 + ${teamCount - firstMatchCount * 2}枠`},
      ...columns.map((nodes, index) => ({
        x: 244 + index * 226,
        name: bracketRoundName(index + 2, totalRounds),
        count: `${nodes.length}試合`
      }))
    ];
    const sourceHtml = sources.map((source) => {
      if (source.kind === "match") {
        const node = {
          x: source.x, y: source.y, match: source.match,
          label: source.match?.match_id || firstRoundName,
          slots: source.slots
        };
        return matchCard(node);
      }
      const data = source.slot.teamId ? team(source.slot.teamId) : null;
      return `<div class="seed-entry" style="left:${source.x}px;top:${source.y}px">
        <span class="seed">${esc(data?.placement_number || "")}</span>
        ${source.slot.teamId ? teamLink(source.slot.teamId) : `<span class="bracket-name pending">${esc(source.slot.label)}</span>`}
      </div>`;
    }).join("");
    const nodeHtml = columns.flatMap((nodes, index) =>
      nodes.map((node) => matchCard(node, index === columns.length - 1))
    ).join("");
    const canvasWidth = totalRounds === 5 ? 1148 : Math.max(460, 244 + (columns.length - 1) * 226 + 214);
    const contentBottom = Math.max(
      ...sources.map((source) => source.y + (source.kind === "match" ? 86 : 30)),
      ...columns.flatMap((nodes) => nodes.map((node) => node.y + 86))
    );
    const canvasHeight = Math.max(totalRounds === 5 ? 1220 : 360, Math.ceil(contentBottom + 40));
    const canvas = $("#bracket-canvas");
    $(".bracket-scroll").setAttribute("aria-label", `${teamCount}チームの対戦表。横スクロールで決勝まで表示`);
    canvas.style.width = `${canvasWidth}px`;
    canvas.style.height = `${canvasHeight}px`;
    canvas.innerHTML = `
      <svg class="bracket-lines" viewBox="0 0 ${canvasWidth} ${canvasHeight}" aria-hidden="true">${edges.map((path) => `<path d="${path}"></path>`).join("")}</svg>
      ${titles.map((item) => `<div class="round-title" style="left:${item.x}px">${esc(item.name)}<span>${esc(item.count)}</span></div>`).join("")}
      ${sourceHtml}${nodeHtml}`;
    const totalMatches = Math.max(0, teamCount - 1);
    $(".bracket-caption").innerHTML = `<strong>${teamCount}チーム / 全${totalMatches}試合</strong><span>1回戦で対戦のないチームは、そのまま2回戦へ進みます。</span><span>線は次の対戦枠につながっています。</span>`;
  }

  function renderSideResults(bracket) {
    const entrants = (bracket?.initial_slots || []).filter(Boolean);
    const planned = (bracket?.slot_sources || []).filter(Boolean);
    const grouped = new Map();
    entrants.forEach((id) => {
      const position = team(id).placement_number || "—";
      const block = position.charAt(0) || "—";
      if (!grouped.has(block)) grouped.set(block, []);
      grouped.get(block).push(id);
    });
    if (!entrants.length && planned.length) {
      $("#league-results").innerHTML = `<p class="side-label">進出予定枠</p>${planned.map((source) =>
        `<div class="side-team"><span></span><span>${esc(source.label)}</span></div>`
      ).join("")}<p class="side-note">順位確定後、同じ枠をチーム名へ置き換えます。</p>`;
      return;
    }
    $("#league-results").innerHTML = bracket ? `<p class="side-label">進出チーム</p>${[...grouped.entries()].sort(([a], [b]) => a.localeCompare(b, "ja")).map(([block, ids]) =>
      `<div class="side-group"><strong>${esc(block)}ブロック</strong>${ids.sort((a, b) => number(team(a).placement_number?.slice(1)) - number(team(b).placement_number?.slice(1))).map((id) =>
        `<div class="side-team"><span>${esc(team(id).placement_number || "")}</span><span role="button" tabindex="0" data-team-id="${esc(id)}">${esc(teamName(id))}</span></div>`
      ).join("")}</div>`
    ).join("")}` : '<p class="side-note">進出チームはまだ確定していません。</p>';
  }

  function switchPage(page) {
    const qualifier = page === "qual";
    $("#qual").hidden = !qualifier;
    $("#detail").hidden = true;
    $("#bracket").hidden = qualifier;
    selectedGroup = null;
    $$(".tab").forEach((button) => {
      const selected = button.dataset.page === page;
      button.setAttribute("aria-selected", String(selected));
      button.tabIndex = selected ? 0 : -1;
    });
    if (!qualifier) renderBracket();
  }

  function installModal() {
    if ($("#team-modal")) return;
    const style = document.createElement("style");
    style.textContent = `
      .team-name[data-team-id]{cursor:pointer}.team-modal{position:fixed;inset:0;z-index:50;display:grid;place-items:center;padding:18px;background:#0b1014cc}
      .team-modal[hidden]{display:none}.team-modal-card{width:min(520px,100%);max-height:85vh;overflow:auto;background:#11181d;border:1px solid #71838f;border-radius:11px;padding:22px;box-shadow:0 15px 45px #0008}
      .team-modal-head{display:flex;justify-content:space-between;gap:16px;align-items:start}.team-modal h2{font-size:20px}.team-modal-close{border:1px solid #71838f;background:transparent;border-radius:6px;padding:7px 10px}
      .team-meta{color:#b6c3cc;line-height:1.9}.member-card{border-top:1px solid #ffffff16;padding-top:12px;margin-top:12px}.member-card strong{display:block;margin-bottom:5px}.member-card p{margin:4px 0;color:#b6c3cc}
    `;
    document.head.appendChild(style);
    document.body.insertAdjacentHTML("beforeend", `<div class="team-modal" id="team-modal" role="dialog" aria-modal="true" aria-labelledby="team-modal-title" hidden>
      <div class="team-modal-card"><div class="team-modal-head"><div><div class="eyebrow">TEAM INFORMATION</div><h2 id="team-modal-title"></h2></div><button class="team-modal-close" type="button">閉じる</button></div><div id="team-modal-body"></div></div>
    </div>`);
    $("#team-modal .team-modal-close").addEventListener("click", closeModal);
    $("#team-modal").addEventListener("click", (event) => {
      if (event.target === $("#team-modal")) closeModal();
    });
  }

  function openTeam(teamId) {
    const data = team(teamId);
    installModal();
    $("#team-modal-title").textContent = data.name;
    const type = data.registration_type === "test" ? "テスト登録（Discord IDなし可）" : "正式登録";
    $("#team-modal-body").innerHTML = `<p class="team-meta">申請番号: ${esc(data.application_number ?? "—")}<br>配置番号: ${esc(data.placement_number || "—")}<br>登録種別: ${esc(type)}</p>
      ${(data.members || []).map((member) => `<div class="member-card"><strong>${esc(member.role || "メンバー")} · ${esc(member.name || "未入力")}</strong>
        <p>所属: ${esc(member.circle || "—")}<br>使用ブキ: ${esc((member.weapons || []).join(" / ") || "—")}</p></div>`).join("") || '<p class="sub">公開メンバー情報はありません。</p>'}`;
    $("#team-modal").hidden = false;
    $("#team-modal .team-modal-close").focus();
  }

  function closeModal() {
    if ($("#team-modal")) $("#team-modal").hidden = true;
  }

  function render() {
    document.title = `${snapshot.tournament_name} | 大会進行`;
    $("h1").textContent = snapshot.tournament_name;
    $(".preview").textContent = "Botデータ連携";
    $(".footer span:last-child").textContent = "Bot確定データを表示 · 変更時に自動更新";
    renderQualifiers();
    if (selectedGroup) openGroup(selectedGroup);
    if (!$("#bracket").hidden) renderBracket();
  }

  function showState(message, error = false) {
    $("#qual-groups").innerHTML = `<p class="sub" role="${error ? "alert" : "status"}">${esc(message)}</p>`;
    $(".preview").textContent = error ? "取得失敗" : "読み込み中";
  }

  async function resolveTournamentId() {
    const params = new URLSearchParams(location.search);
    if (params.get("tournament_id")) return params.get("tournament_id");
    const response = await fetch("/api/otp/tournaments", {cache: "no-store"});
    if (!response.ok) throw new Error(`大会一覧の取得に失敗しました（${response.status}）`);
    const payload = await response.json();
    const items = Array.isArray(payload) ? payload : payload.tournaments || [];
    if (!items.length) throw new Error("表示できる大会データがありません。");
    return items[0].tournament_id;
  }

  async function load() {
    if (loading) return;
    loading = true;
    try {
      const tournamentId = await resolveTournamentId();
      const response = await fetch(`/api/otp/tournaments/${encodeURIComponent(tournamentId)}`, {cache: "no-store"});
      if (!response.ok) throw new Error(response.status === 404 ? "指定した大会データがありません。" : `大会データの取得に失敗しました（${response.status}）`);
      snapshot = await response.json();
      render();
      connectUpdates(tournamentId);
    } catch (error) {
      showState(error.message || "大会データを取得できませんでした。", true);
    } finally {
      loading = false;
    }
  }

  function connectUpdates(tournamentId) {
    if (eventSource || !("EventSource" in window)) {
      if (!fallbackTimer) fallbackTimer = setInterval(load, 60000);
      return;
    }
    eventSource = new EventSource(`/api/otp/tournaments/${encodeURIComponent(tournamentId)}/events`);
    eventSource.addEventListener("update", () => load());
    eventSource.onerror = () => {
      if (!fallbackTimer) fallbackTimer = setInterval(load, 60000);
    };
  }

  document.addEventListener("click", (event) => {
    const teamTarget = event.target.closest("[data-team-id]");
    if (teamTarget) {
      event.preventDefault();
      event.stopPropagation();
      openTeam(teamTarget.dataset.teamId);
      return;
    }
    const groupTarget = event.target.closest("[data-group-id]");
    if (groupTarget) openGroup(groupTarget.dataset.groupId);
  });
  document.addEventListener("keydown", (event) => {
    if ((event.key === "Enter" || event.key === " ") && event.target.matches("[data-team-id]")) {
      event.preventDefault();
      openTeam(event.target.dataset.teamId);
    }
    if (event.key === "Escape") closeModal();
  });
  $$(".tab").forEach((button) => button.addEventListener("click", () => switchPage(button.dataset.page)));
  $("#back").addEventListener("click", () => switchPage("qual"));
  $$(".league-btn").forEach((button) => button.addEventListener("click", () => {
    currentLeague = button.dataset.league;
    $$(".league-btn").forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
    renderBracket();
  }));

  showState("大会データを読み込んでいます。");
  load();
})();
