def get_homepage_template(connector_name: str, app_type: str, environment: str) -> str:
    """
    Returns the HTML template for the homepage of the app connector.
    """
    return f"""
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>{connector_name}</title>
                <link rel="preconnect" href="https://fonts.googleapis.com">
                <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
                <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
                <style>
                    :root {{
                        --primary-color: #0000EE;
                        --background-color: #f8fafc;
                        --card-background: #ffffff;
                        --text-color: #1e293b;
                        --secondary-text: #64748b;
                        --success-color: #10b981;
                        --border-radius: 12px;
                        --shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.05), 0 4px 6px -2px rgba(0, 0, 0, 0.025);
                    }}
                    
                    * {{
                        margin: 0;
                        padding: 0;
                        box-sizing: border-box;
                    }}
                    
                    body {{
                        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
                        background-color: var(--background-color);
                        color: var(--text-color);
                        display: flex;
                        justify-content: center;
                        align-items: center;
                        min-height: 100vh;
                        line-height: 1.6;
                        font-weight: 400;
                    }}
                    
                    .container {{
                        width: 100%;
                        max-width: 480px;
                        padding: 2.5rem;
                        background-color: var(--card-background);
                        border-radius: var(--border-radius);
                        box-shadow: var(--shadow);
                        text-align: center;
                        margin: 1rem;
                    }}
                    
                    .logo {{
                        width: 250px;
                        margin-bottom: 1.5rem;
                        display: block;
                        margin-left: auto;
                        margin-right: auto;
                    }}
                    
                    h1 {{
                        font-size: 1.75rem;
                        font-weight: 600;
                        margin-bottom: 1rem;
                        color: var(--text-color);
                    }}
                    
                    .description {{
                        color: var(--secondary-text);
                        margin-bottom: 1.5rem;
                        font-size: 0.95rem;
                    }}
                    
                    .status-badge {{
                        display: inline-flex;
                        align-items: center;
                        background-color: rgba(16, 185, 129, 0.1);
                        color: var(--success-color);
                        padding: 0.5rem 1rem;
                        border-radius: 2rem;
                        font-weight: 500;
                        margin-bottom: 1.5rem;
                        font-size: 0.875rem;
                    }}
                    
                    .status-badge::before {{
                        content: "";
                        display: inline-block;
                        width: 0.5rem;
                        height: 0.5rem;
                        border-radius: 50%;
                        background-color: var(--success-color);
                        margin-right: 0.5rem;
                    }}
                    
                    .workflow-link {{
                        display: inline-block;
                        margin-top: 0.5rem;
                        text-decoration: none;
                        color: var(--primary-color);
                        font-weight: 500;
                        transition: all 0.2s ease;
                        border: 1px solid rgba(0, 0, 238, 0.2);
                        padding: 0.6rem 1.2rem;
                        border-radius: 0.5rem;
                        font-size: 0.95rem;
                    }}
                    
                    .workflow-link:hover {{
                        background-color: rgba(0, 0, 238, 0.1);
                        transform: translateY(-2px);
                        box-shadow: 0 4px 6px -1px rgba(0, 0, 238, 0.1);
                    }}
                    
                    .arrow {{
                        display: inline-block;
                        margin-left: 0.25rem;
                        font-size: 1.1em;
                        transition: transform 0.2s ease;
                    }}
                    
                    .workflow-link:hover .arrow {{
                        transform: translate(2px, -2px);
                    }}
                    
                    .footer {{
                        margin-top: 2rem;
                        font-size: 0.75rem;
                        color: var(--secondary-text);
                        border-top: 1px solid #f1f5f9;
                        padding-top: 1rem;
                    }}
                    
                    .app-type-wrapper {{
                        margin-bottom: 1.25rem;
                        text-align: center;
                        width: 100%;
                    }}
                    
                    .app-type {{
                        font-size: 0.875rem;
                        color: var(--secondary-text);
                        font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
                        background-color: rgba(100, 116, 139, 0.08);
                        padding: 0.2rem 0.5rem;
                        border-radius: 0.25rem;
                        letter-spacing: 0.025em;
                        display: inline-block;
                    }}
                </style>
            </head>
            <body>
                <div class="container">
                    <img class="logo" src="https://cdn.brandfetch.io/id9Bpy_H9O/theme/dark/logo.svg?c=1dxbfHSJFAPEGdCLU4o5B" alt="Stacksync Logo">
                    <div class="app-type-wrapper">
                        <span class="app-type">{app_type.lower()}</span>
                    </div>
                    <h1>{connector_name}</h1>
                    <div class="status-badge">Running</div>
                    <p class="description">This app connector is up and running. You can now use it in your workflows through the Developer Studio.</p>
                    
                    <a href="https://workflows.stacksync.com" class="workflow-link" target="_blank" rel="noopener">
                        Go to Stacksync Workflows <span class="arrow">↗</span>
                    </a>
                    
                    <div class="footer">
                        Stacksync App Connector | Environment: {environment}
                    </div>
                </div>
            </body>
            </html>
            """