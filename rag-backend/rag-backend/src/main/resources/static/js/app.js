'use strict';
(()=>{
    const conversa = document.getElementById('conversa');
    const dicaFonte = document.getElementById('dica-fonte');
    const formularios = document.querySelectorAll('[data-form]');
    const bolinhas=document.querySelectorAll('[data-busca-total]');

    function buscaTotalMarcada(){
        return bolinhas.length > 0 && bolinhas[0].checked;
    }
    bolinhas.forEach(bolinha=>{
        bolinha.addEventListener('change', ()=>{
            bolinhas.forEach(outra=>{outra.checked=bolinha.checked;});
        });
    });
    function definirEstado(estado){
        document.body.className = estado;
    }
    function bloquearEnvio(bloquear){
        formularios.forEach(form=>{
            form.querySelector('button').disabled = bloquear;
        });
    }
    async function perguntar(texto) {
        const pergunta = texto.trim();
        if(!pergunta){
            return;
        }
        definirEstado('resposta-ativa');
        bloquearEnvio(true);
        esconderDica();
        conversa.innerHTML=Renderizacao.pergunta(pergunta) + Renderizacao.carregando();

        try{
            const dados = await Api.perguntar(pergunta, buscaTotalMarcada());
            conversa.innerHTML = Renderizacao.pergunta(pergunta) + Renderizacao.resposta(dados);
            Renderizacao.esconderCitacoes(conversa.querySelector('.resposta'));
        } catch (erro){
            console.error(erro);
            conversa.innerHTML = Renderizacao.pergunta(pergunta) + Renderizacao.erroDeComunicacao();
        } finally {
            bloquearEnvio(false);
            document.getElementById('pergunta-nova').focus();
        }
    }
    function ajustarAltura(campo){
        campo.style.height = 'auto';
        campo.style.height = campo.scrollHeight + 'px';
    }
    formularios.forEach(form => {
        const campo = form.querySelector('[data-input]');
        form.addEventListener('submit', evento =>{
            evento.preventDefault();
            const texto = campo.value;
            campo.value = '';
            ajustarAltura(campo);
            perguntar(texto);
        });
        campo.addEventListener('keydown', evento =>{
            if (evento.key === 'Enter' && !evento.shiftKey){
                evento.preventDefault();
                form.requestSubmit();
            }
        });
        campo.addEventListener('input', ()=>ajustarAltura(campo));
    });
    document.querySelectorAll('[data-exemplo]').forEach(botao => {
        botao.addEventListener('click', ()=>perguntar(botao.textContent));
    });

    function mostrarDica(frase, x, y){
        dicaFonte.textContent = frase.dataset.fonte;
        dicaFonte.hidden = false;
        const largura = dicaFonte.offsetWidth;
        const esquerda = Math.min(Math.max(8, x-largura/2), window.innerWidth-largura-8);
        dicaFonte.style.left=esquerda+'px';
        dicaFonte.style.top=(y-dicaFonte.offsetHeight-10)+'px';
    }
    function esconderDica(){
        dicaFonte.hidden = true;
    }
    function posicaoDoElemento(frase){
        const caixa = frase.getClientRects()[0];
        return { x: caixa.left + caixa.width / 2, y: caixa.top };
    }

    conversa.addEventListener('mousemove', evento => {
        const frase = evento.target.closest('.citado');
        if (frase){
            mostrarDica(frase, evento.clientX, evento.clientY);
        } else {
            esconderDica();
        }
    });
    conversa.addEventListener('mouseleave', esconderDica);
    conversa.addEventListener('focusin', evento => {
        const frase = evento.target.closest('.citado');
        if (frase){
            const {x,y} = posicaoDoElemento(frase);
            mostrarDica(frase, x, y);
        }
    });
    conversa.addEventListener('focusout', esconderDica);
    document.getElementById('area').addEventListener('scroll', esconderDica);
    document.addEventListener('keydown', evento => {
        if(evento.key === 'Escape'){
            esconderDica();
        }
    });
    document.getElementById('pergunta-inicial').focus();
})();