import discord
import time

import utils

from mongo_models import pull_vote, user


def calculate_pr_points(git_user_id, git_user_name, message):
    try:
        user_doc = user.User.objects.get(git_user_id=git_user_id)
    except user.DoesNotExist as e:
        user_doc = user.User(git_user_id=git_user_id,
                             git_user_name=git_user_name)
        user_doc.save()
    points = user_doc.points
    m_c = len(message.server.members)
    req = 0.7 * m_c
    if points > 0:
        dec = points / (m_c / 50)
        req = req - dec
        if req < 0:
            req = m_c % 10
    return req


def calculate_vote_points(message, votes, required_points):
    try:
        user_doc = user.User.objects.get(discord_id=message.author.id)
        m_c = len(message.server.members)
        points = user_doc.points
        if utils.is_admin(message.author):
            points += (m_c * 4) / (m_c / 10)
        elif utils.is_dev(message.author):
            points += (m_c * 2) / (m_c / 10)

        if points > required_points and votes < 1:
            # an unique vote can't approve a pr
            # min is 2 even for admins
            # grant the 90% of the points
            points = required_points * 90 / 100
        return points, user_doc.discord_name
    except user.DoesNotExist as e:
        return -1
    except Exception as e:
        return -1


async def check_merge(message, discord_client, db_pull_doc, git_repo):
    if db_pull_doc.points >= db_pull_doc.required_points:
        await merge_pr(message, discord_client, git_repo, db_pull_doc)


def get_last_commit(git_repo):
    """
    :param git_repo:
    the repo object
    :return:
    the last commit
    """
    return git_repo.get_commits()[0]


async def get_last_commits(message, discord_client, git_repo):
    """
    :param: git_repo
    the repo object
    :return:
    an embed discord object with the latest 10 commits
    """
    embed = discord.Embed(title='recent secRet dBot commits', type='rich', description='',
                          color=discord.Colour(0xA2746A))
    k = 0
    for commit in git_repo.get_commits():
        if k == 10:
            break
        commit_date = '{0:%Y-%m-%d %H:%M:%S}'.format(commit.commit.author.date)
        embed.add_field(name=commit.commit.message,
                        value=commit.commit.author.name + " - " + commit_date,
                        inline=False)
        k += 1
    await discord_client.send_message(message.channel, embed=embed)


async def git(message, discord_client, git_client, git_repo):
    parts = message.content.split(" ")

    if len(parts) < 2:
        await print_git_help(message, discord_client)
    else:
        if parts[1] == 'commits':
            await get_last_commits(message, discord_client, git_repo)
        elif parts[1] == 'link':
            await link_git(message, discord_client, git_client)
        elif parts[1] == 'search':
            try:
                what = parts[2]
                if what == 'user':
                    try:
                        git_user = git_client.legacy_search_users(parts[3])[0]
                        embed = discord.Embed(title="search result",
                                              type='rich',
                                              description=parts[3],
                                              color=utils.random_color())
                        embed.set_author(name=git_user.login, url='https://github.com/' + git_user.login)
                        embed.set_thumbnail(url=git_user.avatar_url)
                        embed.add_field(name='id', value=str(git_user.id), inline=False)
                        if git_user.type is not None:
                            embed.add_field(name='type', value=git_user.type)
                        embed.add_field(name='followers', value=str(git_user.followers))
                        if git_user.contributions is not None:
                            embed.add_field(name='contributions', value=str(git_user.contributions))
                        if git_user.bio is not None:
                            embed.add_field(name='bio', value=git_user.bio, inline=False)
                        await discord_client.send_message(message.channel, embed=embed)
                    except Exception as e:
                        embed = utils.simple_embed('info', 'no user found', discord.Color.blue())
                        await discord_client.send_message(message.channel, embed=embed)
            except Exception as e:
                # just don't reply
                pass
        elif parts[1] == 'unlink':
            try:
                user.User.objects.get(discord_id=message.author.id).delete()
                embed = utils.simple_embed('success', 'you are now unlinked and your points are back to 0',
                                           discord.Color.green())
                await discord_client.send_message(message.channel, embed=embed)
            except user.DoesNotExist:
                embed = utils.simple_embed('info', 'you are not linked with any github id', discord.Color.blue())
                await discord_client.send_message(message.channel, embed=embed)


async def link_git(message, discord_client, git_client):
    parts = message.content.split(" ")
    try:
        print(message.content)
        git_nick_name = parts[2]
        try:
            u = user.User.objects.get(discord_id=message.author.id)
            embed = utils.simple_embed('info', 'you are already linked to **' + u.git_user_name + '**',
                                       discord.Color.blue())
            await discord_client.send_message(message.channel, embed=embed)
        except user.DoesNotExist:
            try:
                git_user = git_client.legacy_search_users(git_nick_name)[0]
                u = user.User(git_user_id=git_user.id,
                              discord_id=message.author.id,
                              discord_name=message.author.display_name,
                              discord_mention=message.author.mention)
                u.git_user_name = git_user.name
                try:
                    u.save()
                    embed = utils.simple_embed('success', u.git_user_name + ' has been linked to ' +
                                               str(message.author.id),
                                               discord.Color.green())
                    await discord_client.send_message(message.channel, embed=embed)
                except user.NotUniqueError as e:
                    u = user.User.objects.get(git_user_id=git_user.login)
                    embed = utils.simple_embed('error', '**' + git_user.login + '** already linked with: ' +
                                               u.discord_id, discord.Color.red())
                    await discord_client.send_message(message.channel, embed=embed)
            except Exception as e:
                embed = utils.simple_embed('info', 'no user found', discord.Color.blue())
                await discord_client.send_message(message.channel, embed=embed)
    except Exception as e:
        pass


async def merge_pr(message, discord_client, git_repo, pr):
    git_pr = git_repo.get_pull(pr.pull_number)
    if git_pr and git_pr.mergeable:
        embed = discord.Embed(title=pr.pull_title, type='rich', description=pr.user_name,
                              color=utils.random_color())
        for discord_id, vote in pr.votes.items():
            embed.add_field(name=vote['name'],
                            value=str(vote['points']),
                            inline=True)
        await discord_client.send_message(message.channel, embed=embed)

        status = git_pr.merge()
        if status.merged:
            embed = utils.simple_embed('success',
                                       status.sha + ' **merged**. scheduled for next auto-update',
                                       discord.Color.green())
            await discord_client.send_message(message.channel, embed=embed)
        else:
            embed = utils.simple_embed('error',
                                       status.message,
                                       discord.Color.red())
            await discord_client.send_message(message.channel, embed=embed)
    else:
        if git_pr.merge:
            embed = utils.simple_embed('info',
                                       'the pr has already been merged',
                                       discord.Color.blue())
        else:
            embed = utils.simple_embed('error',
                                       'the pr can\'t be merged. check conflicts and resolve them!',
                                       discord.Color.green())
        await discord_client.send_message(message.channel, embed=embed)


async def pr(message, discord_client, git_repo):
    parts = message.content.split(" ")
    if len(parts) == 1:
        await print_pr_help(message, discord_client, git_repo)
    else:
        if parts[1] == 'check':
            try:
                id = int(parts[2])
                try:
                    db_pull_doc = pull_vote.PullVote.objects.get(pull_id=id)
                    if db_pull_doc.points >= db_pull_doc.required_points:
                        await check_merge(message, discord_client, db_pull_doc, git_repo)
                    else:
                        prq = git_repo.get_pull(db_pull_doc.pull_number)
                        await print_pr(message, discord_client, prq, db_pull_doc)
                except pull_vote.DoesNotExist as e:
                    await discord_client.send_message(message.channel,
                                                      embed=utils.simple_embed('error', 'pull request not found',
                                                                               discord.Color.red()))
            except Exception as e:
                await discord_client.send_message(message.channel,
                                                  embed=utils.simple_embed('error', 'usage: !pr check *id',
                                                                           discord.Color.red()))
        elif parts[1] == 'downvote':
            try:
                id = int(parts[2])
                try:
                    db_pull_doc = pull_vote.PullVote.objects.get(pull_id=id)
                    vote_points, user_name = calculate_vote_points(message, len(db_pull_doc.votes),
                                                                   db_pull_doc.required_points)
                    if vote_points < 0:
                        desc = 'link your github with **!linkgit**'
                        await discord_client.send_message(message.channel,
                                                          embed=utils.simple_embed('info', desc, discord.Color.blue()))
                    elif message.author.id in db_pull_doc.votes:
                        await discord_client.send_message(message.channel,
                                                          embed=utils.simple_embed('error', 'you already voted this pr',
                                                                                   discord.Color.red()))
                    else:
                        db_pull_doc.points -= vote_points
                        db_pull_doc.votes[message.author.id] = {
                            'created': time.time(),
                            'name': user_name,
                            'points': vote_points,
                        }
                        db_pull_doc.save()
                        embed = utils.simple_embed('success', '**' + str(vote_points) +
                                                   '** points removed.\nTotal points: **' + str(db_pull_doc.points)
                                                   + '**' + '\nRequired points: **' + str(db_pull_doc.required_points)
                                                   + '**',
                                                   discord.Color.green())
                        await discord_client.send_message(message.channel, embed=embed)
                except pull_vote.DoesNotExist as e:
                    await discord_client.send_message(message.channel,
                                                      embed=utils.simple_embed('error', 'pull request not found',
                                                                               discord.Color.red()))
            except Exception as e:
                await discord_client.send_message(message.channel,
                                                  embed=utils.simple_embed('error', 'usage: !pr downvote *id',
                                                                           discord.Color.red()))
        elif parts[1] == 'upvote':
            try:
                id = int(parts[2])
                try:
                    db_pull_doc = pull_vote.PullVote.objects.get(pull_id=id)
                    vote_points, user_name = calculate_vote_points(message, len(db_pull_doc.votes),
                                                                   db_pull_doc.required_points)
                    if vote_points < 0:
                        desc = 'link your github with **!linkgit**'
                        await discord_client.send_message(message.channel,
                                                          embed=utils.simple_embed('info', desc, discord.Color.blue()))
                    elif message.author.id in db_pull_doc.votes:
                        await discord_client.send_message(message.channel,
                                                          embed=utils.simple_embed('error', 'you already voted this pr',
                                                                                   discord.Color.red()))
                    else:
                        db_pull_doc.points += vote_points
                        if db_pull_doc.points >= db_pull_doc.required_points:
                            db_pull_doc.points = db_pull_doc.required_points

                        db_pull_doc.votes[message.author.id] = {
                            'created': time.time(),
                            'name': user_name,
                            'points': vote_points,
                        }
                        db_pull_doc.save()
                        embed = utils.simple_embed('success', '**' + str(vote_points) +
                                                   '** points added.\nTotal points: **' + str(db_pull_doc.points)
                                                   + '**' + '\nRequired points: **' + str(db_pull_doc.required_points)
                                                   + '**',
                                                   discord.Color.green())
                        await discord_client.send_message(message.channel, embed=embed)

                        if db_pull_doc.points >= db_pull_doc.required_points:
                            try:
                                u = user.User.objects.get(git_user_id=db_pull_doc.user_id)
                                embed = utils.simple_embed('success',
                                                           'pr ' + db_pull_doc.pull_title + ' by **' +
                                                           u.discord_mention + '** has been accepted.',
                                                           discord.Color.green())
                            except Exception as e:
                                embed = utils.simple_embed('success',
                                                           'pr ' + db_pull_doc.pull_title + ' by **' +
                                                           db_pull_doc.user_name + '** has been accepted.',
                                                           discord.Color.green())
                            await discord_client.send_message(message.channel, embed=embed)
                            await check_merge(message, discord_client, db_pull_doc, git_repo)
                except pull_vote.DoesNotExist as e:
                    await discord_client.send_message(message.channel,
                                                      embed=utils.simple_embed('error', 'pull request not found',
                                                                               discord.Color.red()))
            except Exception as e:
                await discord_client.send_message(message.channel,
                                                  embed=utils.simple_embed('error', 'usage: !pr upvote *id',
                                                                           discord.Color.red()))


async def print_git_help(message, discord_client):
    embed = discord.Embed(title='git commands', type='rich', description='-', color=discord.Color(0xA2746A))
    embed.add_field(name='!git commits', value="print latest secRet dBot commits", inline=False)
    embed.add_field(name='!git link *github_nickname', value="link your github id to your discord user", inline=False)
    embed.add_field(name='!git search user *keyword', value="search for users", inline=False)
    embed.add_field(name='!git unlink', value="unlink your github id. will also reset your points", inline=False)
    await discord_client.send_message(message.channel, embed=embed)


async def print_pr(message, discord_client, prq, db_pull_doc):
    embed = discord.Embed(title=prq.user.login, type='rich', description=prq.title, url=prq.user.url,
                          color=discord.Colour(0xA2746A))
    embed.set_thumbnail(url=prq.user.avatar_url)
    created = '{0:%Y-%m-%d %H:%M:%S}'.format(prq.created_at)
    updated = '{0:%Y-%m-%d %H:%M:%S}'.format(prq.updated_at)
    embed.add_field(name='author', value=prq.user.login)
    embed.add_field(name='id', value=str(prq.id))
    embed.add_field(name='created', value=created)
    embed.add_field(name='last update', value=updated)
    embed.add_field(name='commits', value=str(prq.commits))
    embed.add_field(name='comments', value=str(prq.comments))

    embed.add_field(name='points', value=str(db_pull_doc.points))
    embed.add_field(name='required_points', value=str(db_pull_doc.required_points))

    await discord_client.send_message(message.channel, embed=embed)


async def print_pr_help(message, discord_client, git_repo):
    embed = discord.Embed(title='pull requests list', type='rich',
                          description='',
                          color=discord.Colour(0xA2746A))
    embed.add_field(name='!pr check *id', value="try to re-merge after conflict resolution", inline=False)
    embed.add_field(name='!pr upvote *id', value="upvote a pull request", inline=True)
    embed.add_field(name='!pr downvote *id', value="downvote a pull request", inline=True)
    await discord_client.send_message(message.channel, embed=embed)
    await print_pr_list(message, discord_client, git_repo)


async def print_pr_list(message, discord_client, git_repo):
    for prq in git_repo.get_pulls():
        if prq.closed_at:
            # do not add closed
            continue

        try:
            db_pull_doc = pull_vote.PullVote.objects.get(pull_id=prq.id)
        except pull_vote.DoesNotExist as e:
            req_points = calculate_pr_points(prq.user.id, prq.user.login, message)
            db_pull_doc = pull_vote.PullVote(pull_id=prq.id,
                                             user_id=prq.user.id,
                                             user_name=prq.user.login)
            db_pull_doc.pull_number = prq.number
            db_pull_doc.pull_title = prq.title
            db_pull_doc.required_points = req_points
            db_pull_doc.save()

        await print_pr(message, discord_client, prq, db_pull_doc)