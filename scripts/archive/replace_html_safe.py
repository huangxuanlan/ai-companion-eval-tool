import os

filepath = r'E:\提效工具\长文模式生成\server\static\index.html'

with open(filepath, 'r', encoding='utf-8') as f:
    text = f.read()

start_tag = '<div id="tab-role" class="tab-content active">'
end_tag = '<div id="tab-params" class="tab-content">'

s_idx = text.find(start_tag)
e_idx = text.find(end_tag, s_idx)

if s_idx == -1 or e_idx == -1:
    print('Error finding tags!')
    exit(1)

new_content = """<div id="tab-role" class="tab-content active">
        <div class="accordion open">
          <div class="accordion-header" onclick="this.parentElement.classList.toggle('open')"><span>基本信息</span><svg viewBox="0 0 24 24" class="icon chevron" fill="none" stroke="currentColor"><polyline points="6 9 12 15 18 9"/></svg></div>
          <div class="accordion-content">
            <div class="form-item"><label class="form-label">昵称 {{Role_Nickname}}</label><input type="text" id="f-nickname" class="form-control" placeholder="角色昵称"></div>
            <div class="form-grid-2">
              <div class="form-item"><label class="form-label">性别 {{gender}}</label><select id="f-gender" class="form-control"><option>男</option><option>女</option></select></div>
              <div class="form-item"><label class="form-label">年龄 {{age}}</label><input type="number" id="f-age" class="form-control" placeholder="25"></div>
            </div>
            <div class="form-item"><label class="form-label">职业 {{occupation}}</label><input type="text" id="f-occupation" class="form-control" placeholder="金融分析师"></div>
            <div class="form-item"><label class="form-label">人设性格 {{personality}}</label><select id="f-personality" class="form-control"><option>霸道腹黑</option><option>温暖陪伴</option><option>可爱活泼</option><option>理性沉稳</option></select></div>
            <div class="form-item"><label class="form-label">性格类型 {{personal_type}}</label><select id="f-personal-type" class="form-control"><option>ENTJ</option><option>ENFP</option><option>INTJ</option><option>ISFJ</option></select></div>
            <div class="form-item"><label class="form-label">话术风格 {{speaking_style}}</label><input type="text" id="f-speaking-style" class="form-control" placeholder="强势、简短的语气"></div>
            <div class="form-item"><label class="form-label">背景 {{background}}</label><textarea id="f-background" class="form-control" style="min-height:60px" placeholder="出身军人家庭，从小在严格纪律中长大"></textarea></div>
            <div class="form-item"><label class="form-label">兴趣爱好 {{hobby}}</label><input type="text" id="f-hobby" class="form-control" placeholder="书法、品茶、拳击"></div>
          </div>
        </div>

        <div class="accordion">
          <div class="accordion-header" onclick="this.parentElement.classList.toggle('open')"><span>关系与场景</span><svg viewBox="0 0 24 24" class="icon chevron" fill="none" stroke="currentColor"><polyline points="6 9 12 15 18 9"/></svg></div>
          <div class="accordion-content">
            <div class="form-item"><label class="form-label">关系阶段 {{relationship}}</label><select id="f-relationship" class="form-control" onchange="updateRelLinkage()"><option>熟人</option><option>朋友</option><option>暧昧</option><option>恋人</option><option>结婚</option></select></div>
            <div id="rel-linkage-preview" style="font-size:12px;color:var(--text-tertiary);padding:6px 10px;background:var(--bg-hover);border-radius:4px;margin-bottom:10px;display:none"><div>🔗 <strong>自动联动</strong>：</div><div id="rel-linkage-text"></div></div>
            <div class="form-item"><label class="form-label">关系说明 {{relation_info}}</label><input type="text" id="f-relation-info" class="form-control" placeholder="例如：大学同学"></div>
            <div class="form-item"><label class="form-label">亲密边界 {{intimacy_boundary}}</label><textarea id="f-intimacy-boundary" class="form-control" style="min-height:40px" placeholder="仅允许拉手..."></textarea></div>
            <div class="form-grid-2">
              <div class="form-item"><label class="form-label">场景 {{current_scene}}</label><input type="text" id="f-scene" class="form-control" placeholder="公司花园"></div>
              <div class="form-item"><label class="form-label">星期几 {{weekDay}}</label><select id="f-weekday" class="form-control"><option>周一</option><option>周二</option><option>周三</option><option>周四</option><option>周五</option><option>周六</option><option>周日</option></select></div>
            </div>
            <div class="form-item"><label class="form-label">每周日程 {{weekly_schedule}}</label><textarea id="f-weekly-schedule" class="form-control" style="min-height:40px" placeholder="周一至周五白班..."></textarea></div>
            <div class="form-grid-2">
              <div class="form-item"><label class="form-label">时段 {{timeperiod}}</label><select id="f-timeperiod" class="form-control"><option>清晨</option><option>上午</option><option>中午</option><option>下午</option><option>傍晚</option><option>深夜</option></select></div>
              <div class="form-item"><label class="form-label">季节 {{season}}</label><select id="f-season" class="form-control"><option>春季</option><option>夏季</option><option>秋季</option><option>冬季</option></select></div>
            </div>
            <div class="form-item"><label class="form-label">用户昵称 {{user_Nickname}}</label><input type="text" id="f-user-nickname" class="form-control" placeholder="小鹿" value="小鹿"></div>
            <div class="form-grid-2">
              <div class="form-item"><label class="form-label">用户性别 {{user_gender}}</label><select id="f-user-gender" class="form-control"><option>女</option><option>男</option></select></div>
              <div class="form-item"><label class="form-label">用户身份 {{user_identity}}</label><input type="text" id="f-user-identity" class="form-control" placeholder="邻家女孩"></div>
            </div>
            <div class="form-item"><label class="form-label">阶段称呼 {{relation_calling}}</label><input type="text" id="f-relation-calling" class="form-control" placeholder="小姐姐/亲爱的"></div>
          </div>
        </div>

        <div class="accordion">
          <div class="accordion-header" onclick="this.parentElement.classList.toggle('open')"><span>系统模块（自动匹配+可编辑）</span><svg viewBox="0 0 24 24" class="icon chevron" fill="none" stroke="currentColor"><polyline points="6 9 12 15 18 9"/></svg></div>
          <div class="accordion-content">
            <div style="font-size:12px;color:var(--text-secondary);margin-bottom:8px">⚡ 选择 性格+关系+性别 后自动匹配</div>
            <div class="form-item"><label class="form-label">性格行为细化 {{longform_persona}} <span style="font-weight:normal;color:var(--primary-color)">[自动匹配|✏️编辑]</span></label><textarea id="f-sys-persona" class="form-control" style="min-height:60px"></textarea></div>
            <div class="form-item"><label class="form-label">叙事策略 {{longform_narrative_style}}</label><textarea id="f-sys-style" class="form-control" style="min-height:40px"></textarea></div>
            <div class="form-item"><label class="form-label">Few-shot示例 {{longform_few_shot}}</label><textarea id="f-sys-fewshot" class="form-control" style="min-height:40px"></textarea></div>
            <div class="form-item"><label class="form-label">兴趣扩展 {{system_module8}}</label><textarea id="f-sys-module8" class="form-control" style="min-height:40px"></textarea></div>
            <div class="form-item"><label class="form-label">长期记忆画像 {{dialogueStartPrompt}}</label><textarea id="f-sys-startprompt" class="form-control" style="min-height:40px"></textarea></div>
            <div class="form-item"><label class="form-label">对话摘要 {{dialogue_summary}}</label><textarea id="f-sys-summary" class="form-control" style="min-height:40px"></textarea></div>
            <div class="form-item"><label class="form-label">名人设定 {{system_Role_acting}}</label><textarea id="f-sys-role-acting" class="form-control" style="min-height:40px"></textarea></div>
          </div>
        </div>

        <div style="margin-top:16px">
          <div style="display:flex;gap:8px;margin-bottom:8px">
            <button class="btn btn-secondary" style="flex:1" onclick="importConfigExcel()">📥 导入Excel</button>
            <button class="btn btn-secondary" style="flex:1" onclick="exportConfigExcel()">📤 导出变量</button>
            <button class="btn btn-secondary" style="flex:1" onclick="saveAsPreset()">💾 保存模板</button>
          </div>
          <div style="font-size:12px;text-align:center;color:var(--text-secondary)">
            📥 模板下载: <a href="#" style="color:var(--primary-color)">变量表</a> | <a href="#" style="color:var(--primary-color)">打分模板</a> | <a href="#" style="color:var(--primary-color)">对话模板</a>
          </div>
        </div>
      </div>

      """

new_text = text[:s_idx] + new_content + text[e_idx:]

with open(filepath, 'w', encoding='utf-8') as f:
    f.write(new_text)

print("Replacement Complete")
