const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

async function main() {
  let now = 1000000, tick, calls = 0;
  const controls = {
    range: {value:'Past 30 days'}, limit: {value:'Up to 5 articles'},
    'news-cooldown': {}, button: {}, section: {insertAdjacentHTML() {}}
  };
  const store = new Map();
  const context = vm.createContext({
    render() {}, addInput() {}, page:'input', mode:'topic', busy:false,
    topic:'Claude', articles:[], demo:false, result:null, serverResult:null,
    progressText:'', toast() {}, esc:String, ic:() => '',
    Date:{now:() => now}, setInterval:fn => {tick = fn;},
    sessionStorage:{getItem:k => store.get(k), setItem:(k,v) => store.set(k,v)},
    document:{getElementById:id => controls[id], querySelector:s => s === '.sectiontitle' ? controls.section : controls.button},
    api: async (path, body) => {
      calls++;
      assert.equal(body.days, 30);
      assert.equal(body.limit, 5);
      return calls === 1 ? {articles:[], search_status:'rate_limited', retry_after_seconds:30}
        : {articles:[{title:'test fixture',text:'fixture only'}], search_status:'ok', search_provider:'Bing News RSS', search_cached:true};
    }
  });
  vm.runInContext(fs.readFileSync('frontend/search.js', 'utf8'), context);
  await context.addInput();
  assert.equal(controls.button.disabled, true);
  assert.match(controls.button.innerHTML, /30s/);
  await context.addInput();
  assert.equal(calls, 1, 'cooldown must suppress repeat requests');
  now += 31000; tick();
  assert.equal(controls.button.disabled, false);
  await context.addInput();
  assert.equal(calls, 2);
  assert.equal(context.articles.length, 1);
  assert.equal(controls.range.value, 'Past 30 days');
  context.busy = true;
  await context.addInput();
  assert.equal(calls, 2, 'double click must not issue another request');
  console.log('PASS: cooldown, expiry, repeat search, selection preservation, double-click guard');
}
main().catch(error => {console.error(error); process.exitCode = 1;});
