"""Team and employee configuration"""

TEAM_MAPPING = {
    # QA Team
    'Chhavi Bhardwaj': 'QA',
    'Satyarth Singh': 'QA',
    'Nancy Rana': 'QA',
    'Nitin Singh': 'QA',
    'Vineeta Arora': 'QA',
    'Mayank Joshi': 'QA',
    'Kunal Joshi': 'QA',
    'Shubham Negi': 'QA',

    # Development Team
    'Rajesh K': 'Development',
    'Arpit Bhardwaj': 'Development',
    'Archana Pandey': 'Development',
    'Nitesh Bagdi': 'Development',
    'Dhananjai Kalra': 'Development',
    'Pranjal Jindal': 'Development',
    'Shivi Prajapati': 'Development',
    'Mansi Mishra': 'Development',

    # Mobile Team
    'Dolly Munjal': 'Mobile',
    'Sagar Khurana': 'Mobile',
    'Jyoti Dahiya': 'Mobile',

    # Design/Video Team
    'Kaushik Awasthi': 'Design/Video',
    'Furquan Nayyar': 'Design/Video',
    'Akarsh Bahl': 'Design/Video',
    'Gagandeep Kaur': 'Design/Video',
    'Neeraj Kumar': 'Design/Video',

    # Management
    'Arjan Bolwerk': 'Management',

    # User Story
    'Geetika Khanna': 'User Story',

    # Unassigned
    ' ': 'Unassigned',
}

QA_TEAM_MEMBERS = [
    'Chhavi Bhardwaj', 'Satyarth Singh', 'Nancy Rana', 'Nitin Singh',
    'Vineeta Arora', 'Mayank Joshi', 'Kunal Joshi', 'Shubham Negi'
]

TEAMS_LIST = ['QA', 'Development', 'Mobile', 'Design/Video', 'Management', 'User Story']

# Maps team name → analytics profile used in Teams dashboard
TEAM_TYPES = {
    'QA':           'qa',
    'Development':  'dev',
    'Mobile':       'dev',
    'Design/Video': 'design',
    'Management':   'management',
    'User Story':   'management',
}
