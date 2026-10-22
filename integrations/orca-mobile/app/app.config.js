const base=require('./app.json').expo;
module.exports=()=>{
 const team=process.env.SENTRA_IOS_APPLE_TEAM_ID,build=process.env.SENTRA_IOS_BUILD_NUMBER||'1',project=process.env.SENTRA_EAS_PROJECT_ID;
 if(team&&!/^[A-Z0-9]{10}$/.test(team))throw Error('SENTRA_IOS_APPLE_TEAM_ID must contain 10 uppercase letters or digits.');
 if(!/^[1-9][0-9]*$/.test(build))throw Error('SENTRA_IOS_BUILD_NUMBER must be a positive integer.');
 if(project&&!/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(project))throw Error('SENTRA_EAS_PROJECT_ID must be an EAS project UUID.');
 return {...base,...(project?{extra:{eas:{projectId:project}}}:{}),ios:{...base.ios,buildNumber:build,...(team?{appleTeamId:team}:{})}};
};
