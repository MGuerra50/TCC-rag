'use strict';
const Renderizacao = (()=>{
    const CITACAO = /\s*\[([^[\]]*?P[áa]gina\s*\d+[^[\]]*)\]/gi;
    const BLOCOS_COM_TEXTO='p, li';
    const ENTIDADES = {'&': '&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}
    function escapar(valor){
        return String(valor ?? '').replace(/[&<>"']/g, c => ENTIDADES[c]);
    }
    function formatarCitacao(citado){
        const partes = citado.split(',').map(p => p.trim());
        if (partes.length < 6){
            return 'Fonte: ' + citado;
        }
        const [empresa, ano, trimestre, tipo, ...resto]= partes;
        const pagina = resto.pop();
        const escopoBruto = resto.join(', ');
        const escopo = /n[ãa]o declarado/i.test(escopoBruto)?'escopo não declarado':escopoBruto.toLowerCase();
        return `Fonte: ${empresa} - ${trimestre} - ${ano} - ${tipo} - ${escopo} - ${pagina.toLowerCase()}`;
    }
    function esconderCitacoes(container){
        container.querySelectorAll(BLOCOS_COM_TEXTO).forEach(bloco=>{
            const partes = bloco.innerHTML.split(CITACAO);
            if(partes.length === 1){
                return;
            }
            let html ='';
            for (let i = 0;i<partes.length-1;i+=2){
                const trecho=partes[i];
                const fonte = formatarCitacao(partes[i+1]);
                html+=`<span class="citado" tabindex="0" data-fonte="${escapar(fonte)}">${trecho}</span>`;
            }
            bloco.innerHTML=html+partes[partes.length-1];
        });
    }
    function markdown(texto){
        const seguro = escapar(texto);
        if (!window.marked){
            return `<p style="white-space: pre-wrap">${seguro}</p>`;
        }
        return window.marked.parse(seguro);
    }
    function fontes(lista){
        if (!lista||lista.length===0){
            return '';
        }
        const linhas = lista.map( f=>`
            <tr>
                <td>${escapar(f.company)}</td><td>${escapar(f.year)}</td><td>${escapar(f.quarter)}</td>
                <td>${escapar(f.docType)}</td><td>${escapar(f.pageNumber)}</td>
                <td>${escapar(f.scope)}</td><td>${escapar(escapar(f.scale))}</td>
            </tr>    
        `).join('');
        return `
            <details>
                <summary>Fontes consultas (${lista.length})</summary>
                <div class="tabela">
                    <table>
                        <thead>
                            <tr><th>Empresa</th><th>Ano</th><th>Trimestre</th><th>Tipo</th><th>Página</th><th>Escopo</th><th>Escala</th></tr>
                        </thead>
                        <tbody>${linhas}</tbody>
                    </table>
                </div>
            </details>
        `;
    }
    function filtros(f){
        if (!f){
            return '';
        }
        const partes = [];
        if (f.companies?.length){
            partes.push(`empresa <b>${escapar(f.companies.join(', '))}</b>`);
        }
        if (f.years?.length){
            partes.push(`ano <b>${escapar(f.years.join(', '))}</b>`);
        }
        if (f.quarters?.length){
            partes.push(`trimestre <b>${escapar(f.quarters.join(', '))}</b>`);
        }
        if (partes.length===0){
            return '';
        }
        const inferido = f.periodWasInferred?' (período inferido) ': '';
        return `<p class="filtros">Filtros aplicados: ${partes.join(' • ')}${inferido}</p>`;
    }

    function pergunta(texto){
        return `<div class="pergunta"><p>${escapar(texto)}</p></div>`;
    }

    function carregando(){
        return `<p class="carregando">Consultando os relatórios<span>.</span><span>.</span><span>.</span></p>`;
    }

    function resposta(dados){
        const ehErro = !dados.sources?.length && !dados.availableCompanies;
        return `
            <article class="resposta${ehErro ? ' erro' : ''}">
                ${markdown(dados.answer)}
                ${fontes(dados.sources)}
                ${filtros(dados.appliedFilters)}
            </article>
        `;
    }

    function erroDeComunicacao(){
        return '<article class="resposta erro"><p>Não foi possível se comunicar com o sistema.</p></article>';
    }
    return {pergunta, carregando, resposta, erroDeComunicacao, esconderCitacoes};
})();