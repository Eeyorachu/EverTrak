EVERTRAK — CLOUD VERSION FOR RENDER

Public branding:
- Login page says only EverTrak / Bid Tracking.
- No company name is exposed on the unauthenticated page.
- The authenticated app is also branded EverTrak.

DEPLOY
1. Create a private GitHub repository and upload all files in this folder to the repository root.
2. In Render, create a New Blueprint and connect that repository.
3. Render reads render.yaml and creates:
   - the EverTrak web service
   - the PostgreSQL database
4. During Blueprint setup Render will ask for APP_PASSWORD. Enter the shared password you want staff to use.
   Do NOT put that password into GitHub.
5. Deploy. Open the generated Render web address and sign in.

The SECRET_KEY is generated automatically by Render and DATABASE_URL is wired automatically from the database.

IMPORTANT
The included Blueprint currently uses Render's free service/database plans for initial setup/testing.
Before relying on EverTrak for important company bid records, review Render's current paid database backup/retention options and choose the level appropriate for your business.

DATA
All users share the PostgreSQL database. Data is not stored in individual browsers.

SECURITY
The application uses an HTTP-only secure session cookie after the shared password is entered.
Anyone with the shared password can access all bid data and change history, so change the password if it is disclosed.

UPDATES
Push future code changes to the connected Git repository; Render can redeploy from it.
