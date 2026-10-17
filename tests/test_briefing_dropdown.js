const fs=require('fs'),vm=require('vm'),assert=require('assert');
const el={innerHTML:'',textContent:'',classList:{add(){},remove(){}},scrollIntoView(){}};
const c={document:{getElementById:()=>el,querySelector:()=>null,querySelectorAll:()=>[]},window:{scrollTo(){}},setTimeout(){},console};
vm.createContext(c);
for(const p of ['frontend/app.js','frontend/backend.js'])vm.runInContext(fs.readFileSync(p,'utf8'),c);
c.fixture={fictional_demo:false,articles:[{id:'A1',title:'Source',text:'Article',date:''}],nlp:{sentences:[],retained:[],duplicates:[],method:'TF-IDF'},timeline:{events:[]},warnings:[],elapsed_seconds:1,summary:{mode:'extractive',claims:Array.from({length:8},(_,i)=>({text:'Claim '+i,evidence_ids:[]})),baseline:Array.from({length:8},(_,i)=>({text:'Baseline '+i,evidence_ids:[]})),evidence_count:8,omitted_sentences:0}};
vm.runInContext("adoptResult(fixture);page='summary';render()",c);
for(const [choice,count] of [['short',3],['detailed',8],['medium',5],['short',3]]){
 const handler=vm.runInContext('summaryView()',c).match(/onchange="([^"]+)"/)[1];
 c.selectElement={value:choice,length:3};
 // Inline event handlers resolve element properties before global names.
 vm.runInContext(`(function(){with(this){${handler}}}).call(selectElement)`,c);
 assert.equal(vm.runInContext('summaryLength',c),choice);
 assert.equal(vm.runInContext('currentClaims().length',c),count);
 assert.equal(c.selectElement.length,3,'Dropdown options must survive changes');
 assert(vm.runInContext('summaryView()',c).includes(`<option selected>${choice}</option>`));
}
vm.runInContext("setSummaryLength('invalid')",c);assert.equal(vm.runInContext('summaryLength',c),'short');
console.log('PASS: short/medium/detailed switching, selected option, point counts and inline-handler scope');
