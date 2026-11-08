/* Render the verified Quarto deliverable as a vector PDF with print typography.
   Usage: NODE_PATH=<directory containing playwright> node scripts/render_pdf.cjs
   CHROME_PATH is optional when Chrome is installed in its standard Windows path. */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {pathToFileURL} = require('node:url');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const sha = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const read = file => JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, ''));
const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

(async () => {
  const source = path.join(root, 'reports/CRM_DIAGNOSTIC.html');
  const render = read(path.join(root, 'reports/RENDER_MANIFEST.json'));
  const analysis = read(path.join(root, 'report/data/analysis_manifest.json'));
  if (sha(source) !== render.html_sha256 || sha(path.join(root, 'report/data/analysis_manifest.json')) !== render.analysis_manifest_sha256)
    throw new Error('Verified HTML or analysis manifest changed');
  for (const name of ['diagnostics','experiment','experiment_checks','policy']) {
    if (sha(path.join(root, `report/data/${name}.json`)) !== analysis[`${name}_sha256`])
      throw new Error(`Aggregate changed: ${name}`);
  }
  const aggregate = read(path.join(root, 'report/data/policy.json'));
  const selected = aggregate.final.find(row => row.policy_id === aggregate.selection.chosen_policy.id);
  const output = path.join(root, 'output/pdf/CRM_FINAL_REPORT.pdf');
  const temp = path.join(root, 'tmp/pdfs');
  fs.mkdirSync(path.dirname(output), {recursive:true});
  fs.mkdirSync(path.join(temp, 'figures'), {recursive:true});
  const browser = await chromium.launch({headless:true, executablePath:process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try {
    const context = await browser.newContext({viewport:{width:1280,height:1000}, offline:true});
    const page = await context.newPage();
    const errors = [], external = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('request', r => {if (/^https?:/.test(r.url())) external.push(r.url());});
    await page.goto(pathToFileURL(source).href);
    await page.waitForFunction(() => [...document.querySelectorAll('.plotly-graph-div')].length === 14 && [...document.querySelectorAll('.plotly-graph-div')].every(el => el._fullLayout));
    const chartData = await page.evaluate(async () => {
      const items = [];
      for (const el of document.querySelectorAll('.plotly-graph-div')) {
        const update = {width:850, autosize:false, 'font.size':14.5, 'title.font.size':23, 'legend.font.size':13.5};
        for (const key of Object.keys(el.layout)) {
          if (/^[xy]axis\d*$/.test(key)) {
            update[`${key}.tickfont.size`] = 14.5;
            update[`${key}.title.font.size`] = 14.5;
          }
        }
        (el.layout.annotations || []).forEach((a,i) => update[`annotations[${i}].font.size`] = Math.max(a.font?.size || 12,13.5));
        // Additional footer room prevents enlarged multi-line notes from clipping.
        update.height = el.layout.height + 20;
        update['margin.b'] = Math.max(el.layout.margin?.b || 0,135);
        await Plotly.relayout(el, update);
        await Plotly.restyle(el, {'textfont.size':13.5});
        const url = await Plotly.toImage(el, {format:'svg',width:850,height:el.layout.height});
        const svg = decodeURIComponent(url.slice(url.indexOf(',')+1));
        items.push({id:el.id.replace(/^crm-/,''), svg, height:el.layout.height});
      }
      return items;
    });
    chartData.forEach(row => fs.writeFileSync(path.join(temp,'figures',row.id+'.svg'),row.svg));
    const sections = await page.evaluate(charts => {
      const main = document.querySelector('main.content');
      if (!main) throw new Error('Quarto main content is missing');
      const sections = [...main.querySelectorAll(':scope > section.level2')];
      const result = sections.map((section,sectionIndex) => {
        const copy = section.cloneNode(true);
        copy.classList.add('report-section');
        if ([0,4,8].includes(sectionIndex)) copy.classList.add('chapter-start');
        // Short ASCII destinations avoid oversized PDF Name tokens for Korean IDs.
        copy.id = `pdf-section-${sectionIndex+1}`;
        copy.querySelectorAll('section[id],h1[id],h2[id],h3[id],h4[id]').forEach((el,i)=>{
          el.id=`pdf-heading-${sectionIndex+1}-${i+1}`;
        });
        copy.querySelectorAll('.figure-card').forEach(card => {
          const id = card.querySelector('.plotly-graph-div').id.replace(/^crm-/,'');
          const source = charts.find(row => row.id===id);
          if (!source) throw new Error('Missing static figure: '+id);
          card.innerHTML = source.svg;
          card.className = 'figure-card';
          card.setAttribute('data-figure-id',id);
        });
        copy.querySelectorAll('script,.anchorjs-link,.quarto-anchor').forEach(el=>el.remove());
        copy.querySelectorAll('p').forEach(el=>{
          if (el.textContent.trim()==='On narrow screens, scroll charts horizontally.') el.remove();
        });
        const opening=[];
        for (const child of [...copy.children]) {
          if (!['H2','P'].includes(child.tagName)) break;
          opening.push(child);
        }
        if (opening.length>1) {
          const intro=document.createElement('div'); intro.className='section-intro';
          copy.insertBefore(intro,opening[0]); opening.forEach(child=>intro.appendChild(child));
        }
        return {id:copy.id,title:copy.querySelector('h2').textContent.trim(),html:copy.outerHTML};
      });
      return {items:result,sourceTables:main.querySelectorAll('table').length,
              outputTables:result.reduce((n,item)=>n+(item.html.match(/<table\b/g)||[]).length,0)};
    }, chartData);
    if (sections.items.length !== 13 || sections.sourceTables!==17 || sections.outputTables!==17 || chartData.length!==14)
      throw new Error('Section/table/chart completeness check failed');
    const krw = v => (v>0?'+':'')+Math.round(v).toLocaleString('en-US');
    const decision = selected.rollout.decision === 'candidate' ? 'Rollout candidate in the synthetic environment' : selected.rollout.decision === 'hold' ? 'Hold the policy' : 'Modify or collect more evidence';
    const cover = `<section class="cover"><div class="cover-kicker">CRM RETENTION LAB / FINAL REPORT</div>
      <h1>After the first purchase,<br>who should receive which CRM treatment?</h1>
      <div class="cover-subtitle">Repurchase diagnosis, a three-arm experiment, and customer policies under budget, contact, and side-effect constraints</div>
      <div class="cover-rule"></div><p>Fictional D2C coffee retailer · Marketing planning portfolio</p>
      <div class="cover-grid"><div class="cover-card"><span class="cover-number">${krw(selected.primary.estimate)} KRW</span><span class="cover-label">Incremental contribution profit per eligible customer</span></div>
      <div class="cover-card"><span class="cover-number">${(100*selected.exposure.contact_fraction).toFixed(1)}%</span><span class="cover-label">Contact rate · 30% cap</span></div>
      <div class="cover-card"><span class="cover-number">${selected.n.toLocaleString('en-US')}</span><span class="cover-label">Independent final-evaluation customers</span></div></div>
      <div class="cover-decision"><p><strong>Final decision: ${decision}</strong></p><p>Budget, contact, and both side-effect criteria are met. However, the 95% interval for incremental contribution profit is ${krw(selected.primary.ci_lower)} to ${krw(selected.primary.ci_upper)} KRW, so evidence is insufficient to establish a profit improvement.</p></div>
      <div class="cover-meta">2026.11.08 · Synthetic-data analysis<br>Training 15,284 / validation 15,167 / final evaluation 15,363 customers<br>The policy was locked on validation data before independent final evaluation.<br>Source: Plotly + Quarto interactive report · This is the static print version.</div></section>`;
    const contents = `<section class="contents"><h2>Reading guide</h2><p>Repurchase diagnosis, the three-arm experiment, and customer-level policy evaluation.</p>
      <div class="contents-grid">${sections.items.map(row=>`<div class="toc-entry"><a href="#${escape(row.id)}">${escape(row.title)}</a></div>`).join('')}</div>
      <div class="reader-note"><p><strong>Report scope</strong></p><p>Sections 1–4 diagnose natural repurchase; sections 5–8 report average training-experiment effects; sections 9–12 independently evaluate customer policies; section 13 covers interpretation and references.</p>
      <p>All 13 sections, 17 tables, and 14 charts are included. PDF charts are vector images. Legend toggles and hover details described in the text are available in the original HTML.</p>
      <p>Read each table and chart with its stated window and denominator. Policy profit and side effects use the full final-evaluation population.</p></div></section>`;
    const css = fs.readFileSync(path.join(root,'report/pdf.css'),'utf8');
    const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>CRM Retention Lab - Final Report</title><style>${css}</style></head><body>${cover}${contents}${sections.items.map(row=>row.html).join('\n')}</body></html>`;
    fs.writeFileSync(path.join(temp,'print-report.html'),html);
    await page.setContent(html, {waitUntil:'load'});
    await page.emulateMedia({media:'print'});
    await page.evaluate(()=>document.fonts.ready);
    await page.pdf({path:output, format:'A4', preferCSSPageSize:true, printBackground:true, tagged:true, outline:true,
      displayHeaderFooter:true,headerTemplate:'<div></div>',
      footerTemplate:'<div style="width:100%;padding:0 14mm;display:flex;justify-content:space-between;color:#68778b;font-family:Arial,sans-serif;font-size:8px;"><span>CRM RETENTION LAB · SYNTHETIC DATA</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>'});
    if (errors.length || external.length) throw new Error(JSON.stringify({errors,external}));
    const manifest = {format:'pdf',source_html:'reports/CRM_DIAGNOSTIC.html',source_html_sha256:sha(source),
      analysis_manifest_sha256:sha(path.join(root,'report/data/analysis_manifest.json')),
      source_sections:sections.items.map(row=>({id:row.id,title:row.title})),section_count:sections.items.length,
      table_count:sections.outputTables,figure_count:chartData.length,print_figure_width_px:850,
      minimum_axis_font_px:14.5,minimum_annotation_font_px:13.5,external_requests:external,render_errors:errors,
      source_sha256:{'scripts/render_pdf.cjs':sha(__filename),'report/pdf.css':sha(path.join(root,'report/pdf.css'))},
      pdf_sha256:sha(output),output:'output/pdf/CRM_FINAL_REPORT.pdf',bytes:fs.statSync(output).size};
    fs.writeFileSync(path.join(root,'output/pdf/PDF_MANIFEST.json'),JSON.stringify(manifest,null,2)+'\n');
    console.log(JSON.stringify({output,bytes:manifest.bytes,sections:manifest.section_count,tables:manifest.table_count,charts:manifest.figure_count}));
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
