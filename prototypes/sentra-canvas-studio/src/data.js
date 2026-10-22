export const dots = [
  {id:'atlas',name:'Atlas',color:'blue',role:'Estratégia e pesquisa',description:'Transforma perguntas abertas em caminhos claros. Pesquisa, conecta ideias e organiza os próximos passos.',state:'Disponível'},
  {id:'luma',name:'Luma',color:'mint',role:'Design e experiência',description:'Cuida dos detalhes que tornam uma ideia simples de usar. Interfaces, identidade e experiências digitais.',state:'Disponível'},
  {id:'nexo',name:'Nexo',color:'purple',role:'Código e desenvolvimento',description:'Da arquitetura ao último ajuste. Constrói e documenta soluções junto com você.',state:'Disponível'},
];
export const conversations = [
  {id:'launch',title:'Um novo começo para o Studio',dot:'atlas',space:'Studio',time:'Agora',preview:'Uma experiência mais clara, do primeiro clique à entrega.'},
  {id:'identity',title:'Uma identidade com personalidade',dot:'luma',space:'Studio',time:'Ontem',preview:'Tipografia, cores e os pequenos detalhes que fazem diferença.'},
  {id:'architecture',title:'Organizando a próxima versão',dot:'nexo',space:'Produto',time:'Ontem',preview:'Uma base simples para construir com confiança.'},
];
export const initialDocuments = [
  {id:'brief',title:'Direção do Studio',type:'Documento',edited:'há 2 min',content:'# Direção do Studio\n\nUm espaço para pensar, criar e dar continuidade.\n\n## O que estamos construindo\n\nUma experiência que coloca a conversa no centro e mantém as ferramentas ao alcance. Cada escolha deve tornar o próximo passo mais claro.\n\n## Princípios\n\n1. Clareza antes de quantidade.\n2. Contexto sempre por perto.\n3. Personalidade nos detalhes.\n\n## Próximos passos\n\nRevisar a navegação, explorar a conversa e validar os dois temas.'},
  {id:'research',title:'Notas de pesquisa',type:'Documento',edited:'há 1 hora',content:'# Notas de pesquisa\n\nAs pessoas alternam entre conversar, consultar referências e produzir documentos.\n\n## Oportunidades\n\n- Manter o rascunho ao trocar de ferramenta.\n- Explicar o estado do trabalho com palavras simples.\n- Aproximar decisões e materiais de apoio.'},
  {id:'checklist',title:'Checklist de lançamento',type:'Checklist',edited:'ontem',content:'# Checklist de lançamento\n\n☑ Definir a direção visual\n☑ Organizar o protótipo\n☐ Avaliar as telas\n☐ Recolher feedback\n☐ Planejar a implementação'},
];
export const states = {
  queued:{label:'Na fila',tone:'neutral'},running:{label:'Trabalhando',tone:'blue'},approval:{label:'Precisa da sua aprovação',tone:'amber'},done:{label:'Concluído',tone:'green'},failed:{label:'Não foi possível concluir',tone:'red'},uncertain:{label:'Resultado não confirmado',tone:'amber'},paused:{label:'Pausado',tone:'neutral'},disconnected:{label:'Conexão interrompida',tone:'red'},cancelled:{label:'Cancelado',tone:'neutral'}
};
