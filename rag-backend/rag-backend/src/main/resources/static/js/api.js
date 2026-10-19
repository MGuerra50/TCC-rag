'use strict';
const Api=(()=>{
    const ENDPOINT = '/api/ask';
    async function perguntar(pergunta, buscaTotal){
        const resposta = await fetch(ENDPOINT, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({question: pergunta, fullSearch: buscaTotal === true})
        });
        if (!resposta.ok){
            const corpo = await resposta.json().catch(()=>null);
            if(corpo?.message){
                return { question: pergunta, answer: corpo.message, sources: [], availableCompanies: null, appliedFilters:null};
            }
            throw new Error('HTTP ' + resposta.status);
        }
        return resposta.json();
    }
    return {perguntar};
})();